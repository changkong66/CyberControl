from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c12 import (
    PublicationCommitCommandV2,
    ReleaseDerivationCommandV2,
)
from liyans_contracts.topic4_common import AggregateDecision, ClaimKind, VerificationModule
from liyans_contracts.verification import VerificationState
from sqlalchemy import func, select, text

from liyans.core.tenant import TenantContext, TenantIsolationError, tenant_scope
from liyans.domains.release.engine import (
    AuthorizationExpiredError,
    AuthorizationReplayError,
    C12ReleaseService,
    PublicationIntegrityError,
    ReleaseError,
)
from liyans.domains.release.postgres_repository import PostgresAtomicReleaseRepository
from liyans.domains.verification.records import build_topic4_record, record_integrity_valid
from liyans.domains.verification.release_models import (
    Topic4PublicationBatchModel,
    Topic4PublicStreamEventModel,
    Topic4ReleaseAuthorizationConsumptionModel,
    Topic4ReleaseAuthorizationModel,
)
from liyans.infrastructure.database import SessionExecutionContext
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.models import AuditEventModel, OutboxMessageModel
from liyans.infrastructure.persistence.postgres_outbox import PostgresOutboxRepository

from .topic4_runtime_support import (
    PartiallySupportedHandler,
    build_publication_request,
    build_release_authorization,
    build_topic4_runtime_fixture,
    finalize_release_report,
)

pytestmark = pytest.mark.integration


class _FailAfterOutboxAppend(PostgresOutboxRepository):
    async def append(self, session, message) -> None:
        await super().append(session, message)
        raise RuntimeError("injected failure after transactional Outbox append")


async def _provision_foreign_tenant(fixture) -> TenantContext:
    tenant_id = f"it-foreign-{uuid4().hex[:16]}"
    context = TenantContext(
        tenant_id=tenant_id,
        subject_ref="subject:foreign-integration",
        roles=frozenset({"integration"}),
        scopes=frozenset({"topic4:release"}),
        trace_id="f" * 32,
    )
    async with fixture.migrator.transaction(
        context=SessionExecutionContext(
            tenant_id=tenant_id,
            subject_ref="system:integration-provisioner",
            trace_id=context.trace_id,
        )
    ) as session:
        await session.execute(
            text(
                "INSERT INTO tenants "
                "(tenant_id, slug, display_name, oidc_issuer, oidc_tenant_claim) "
                "VALUES (:tenant_id, :slug, :display_name, :issuer, :tenant_claim)"
            ),
            {
                "tenant_id": tenant_id,
                "slug": tenant_id,
                "display_name": "Foreign Integration Tenant",
                "issuer": "https://foreign-issuer.test",
                "tenant_claim": tenant_id,
            },
        )
    return context


def _derivation_command(
    fixture,
    verification_id,
    *,
    idempotency_key: str,
    requested_release_mode: str = "FULL",
    requested_block_ids: list[str] | None = None,
    ttl_seconds: int = 120,
) -> ReleaseDerivationCommandV2:
    context = fixture.context
    return build_topic4_record(
        ReleaseDerivationCommandV2,
        trace_id=context.trace_id,
        tenant_id=context.tenant_id,
        version_cas=1,
        created_at=datetime.now(UTC),
        immutable=True,
        schema_version="release.derivation.command.v2",
        derivation_command_id=uuid5(
            NAMESPACE_URL,
            f"topic4:c12:test:derive:{context.tenant_id}:{idempotency_key}",
        ),
        verification_id=verification_id,
        requested_release_mode=requested_release_mode,
        requested_block_ids=requested_block_ids or [],
        ttl_seconds=ttl_seconds,
        idempotency_key_sha256=canonical_sha256({"idempotency_key": idempotency_key}),
    )


def _commit_command(
    fixture, authorization_id, *, idempotency_key: str
) -> PublicationCommitCommandV2:
    context = fixture.context
    return build_topic4_record(
        PublicationCommitCommandV2,
        trace_id=context.trace_id,
        tenant_id=context.tenant_id,
        version_cas=1,
        created_at=datetime.now(UTC),
        immutable=True,
        schema_version="publication.commit.command.v2",
        commit_command_id=uuid5(
            NAMESPACE_URL,
            f"topic4:c12:test:commit:{context.tenant_id}:{idempotency_key}",
        ),
        authorization_id=authorization_id,
        idempotency_key_sha256=canonical_sha256({"idempotency_key": idempotency_key}),
    )


@pytest.mark.asyncio
async def test_c12_postgres_rejects_expiry_tampering_replay_and_cross_tenant_access(
    postgres_runtime,
    tmp_path: Path,
) -> None:
    fixture = await build_topic4_runtime_fixture(
        postgres_runtime,
        tmp_path,
        instance_suffix="release-security",
    )
    foreign_context = await _provision_foreign_tenant(fixture)

    with tenant_scope(fixture.context):
        _request, finalized = await finalize_release_report(fixture)
        issued_at = datetime.now(UTC)
        expires_at = issued_at + timedelta(minutes=5)
        clock = {"now": issued_at}
        repository = PostgresAtomicReleaseRepository(
            fixture.database,
            fixture.outbox,
            instance_id="topic4-release-security",
            clock=lambda: clock["now"],
        )
        service = C12ReleaseService(repository, fixture.artifact_store)

        expired_authorization = build_release_authorization(
            fixture,
            finalized.report,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        expired_request = build_publication_request(
            fixture,
            expired_authorization,
            finalized.report,
        )
        await service.issue_authorization(expired_authorization, now=issued_at)
        clock["now"] = expires_at + timedelta(seconds=1)
        with pytest.raises(AuthorizationExpiredError):
            await service.publish(expired_request, now=issued_at)

        clock["now"] = issued_at
        _second_request, second_finalized = await finalize_release_report(fixture)
        authorization = build_release_authorization(
            fixture,
            second_finalized.report,
            issued_at=issued_at,
        )
        publication_request = build_publication_request(
            fixture,
            authorization,
            second_finalized.report,
        )
        await service.issue_authorization(authorization, now=issued_at)
        tampered_report = second_finalized.report.model_copy(update={"report_sha256": "f" * 64})
        tampered_request = build_publication_request(
            fixture,
            authorization,
            tampered_report,
        )
        with pytest.raises(PublicationIntegrityError, match="report record SHA"):
            await service.publish(tampered_request, now=issued_at)

        published = await service.publish(publication_request, now=issued_at)
        changed_replay = replace(publication_request, request_sha256="e" * 64)
        with pytest.raises(AuthorizationReplayError):
            await repository.consume_and_publish(
                changed_replay,
                published.public_artifact,
                published.public_event.payload_artifact,
            )

        async with fixture.database.transaction(context=current_session_context()) as session:
            expired_consumptions = await session.scalar(
                select(func.count())
                .select_from(Topic4ReleaseAuthorizationConsumptionModel)
                .where(
                    Topic4ReleaseAuthorizationConsumptionModel.tenant_id
                    == fixture.context.tenant_id,
                    Topic4ReleaseAuthorizationConsumptionModel.authorization_id
                    == expired_authorization.authorization_id,
                )
            )

    with tenant_scope(foreign_context):
        async with fixture.database.transaction(context=current_session_context()) as session:
            visible_authorizations = await session.scalar(
                select(func.count())
                .select_from(Topic4ReleaseAuthorizationModel)
                .where(
                    Topic4ReleaseAuthorizationModel.authorization_id
                    == authorization.authorization_id
                )
            )
            visible_batches = await session.scalar(
                select(func.count())
                .select_from(Topic4PublicationBatchModel)
                .where(
                    Topic4PublicationBatchModel.authorization_id == authorization.authorization_id
                )
            )
        with pytest.raises(TenantIsolationError):
            await service.publish(publication_request, now=issued_at)

    assert expired_consumptions == 0
    assert visible_authorizations == 0
    assert visible_batches == 0


@pytest.mark.asyncio
async def test_c12_postgres_outbox_failure_rolls_back_every_publication_record(
    postgres_runtime,
    tmp_path: Path,
) -> None:
    fixture = await build_topic4_runtime_fixture(
        postgres_runtime,
        tmp_path,
        instance_suffix="release-rollback",
    )

    with tenant_scope(fixture.context):
        _request, finalized = await finalize_release_report(fixture)
        issued_at = datetime.now(UTC)
        authorization = build_release_authorization(
            fixture,
            finalized.report,
            issued_at=issued_at,
        )
        publication_request = build_publication_request(
            fixture,
            authorization,
            finalized.report,
        )
        normal_repository = PostgresAtomicReleaseRepository(
            fixture.database,
            fixture.outbox,
            instance_id="topic4-release-rollback-normal",
            clock=lambda: issued_at,
        )
        normal_service = C12ReleaseService(normal_repository, fixture.artifact_store)
        await normal_service.issue_authorization(authorization, now=issued_at)

        async with fixture.database.transaction(context=current_session_context()) as session:
            baseline_outbox = await session.scalar(
                select(func.count()).select_from(OutboxMessageModel)
            )
            baseline_audit = await session.scalar(select(func.count()).select_from(AuditEventModel))

        failing_service = C12ReleaseService(
            PostgresAtomicReleaseRepository(
                fixture.database,
                _FailAfterOutboxAppend(fixture.database),
                instance_id="topic4-release-rollback-failpoint",
                clock=lambda: issued_at,
            ),
            fixture.artifact_store,
        )
        with pytest.raises(RuntimeError, match="injected failure"):
            await failing_service.publish(publication_request, now=issued_at)

        async with fixture.database.transaction(context=current_session_context()) as session:
            failed_consumptions = await session.scalar(
                select(func.count())
                .select_from(Topic4ReleaseAuthorizationConsumptionModel)
                .where(
                    Topic4ReleaseAuthorizationConsumptionModel.authorization_id
                    == authorization.authorization_id
                )
            )
            failed_batches = await session.scalar(
                select(func.count())
                .select_from(Topic4PublicationBatchModel)
                .where(
                    Topic4PublicationBatchModel.authorization_id == authorization.authorization_id
                )
            )
            failed_events = await session.scalar(
                select(func.count())
                .select_from(Topic4PublicStreamEventModel)
                .where(
                    Topic4PublicStreamEventModel.authorization_id == authorization.authorization_id
                )
            )
            failed_outbox = await session.scalar(
                select(func.count()).select_from(OutboxMessageModel)
            )
            failed_audit = await session.scalar(select(func.count()).select_from(AuditEventModel))

        published = await normal_service.publish(publication_request, now=issued_at)
        async with fixture.database.transaction(context=current_session_context()) as session:
            committed_consumptions = await session.scalar(
                select(func.count())
                .select_from(Topic4ReleaseAuthorizationConsumptionModel)
                .where(
                    Topic4ReleaseAuthorizationConsumptionModel.authorization_id
                    == authorization.authorization_id
                )
            )
            committed_batches = await session.scalar(
                select(func.count())
                .select_from(Topic4PublicationBatchModel)
                .where(
                    Topic4PublicationBatchModel.authorization_id == authorization.authorization_id
                )
            )
            committed_events = await session.scalar(
                select(func.count())
                .select_from(Topic4PublicStreamEventModel)
                .where(
                    Topic4PublicStreamEventModel.authorization_id == authorization.authorization_id
                )
            )
            committed_outbox = await session.scalar(
                select(func.count()).select_from(OutboxMessageModel)
            )
            committed_audit = await session.scalar(
                select(func.count()).select_from(AuditEventModel)
            )

    assert failed_consumptions == 0
    assert failed_batches == 0
    assert failed_events == 0
    assert failed_outbox == baseline_outbox
    assert failed_audit == baseline_audit
    assert published.batch.state.value == "COMMITTED"
    assert committed_consumptions == 1
    assert committed_batches == 2
    assert committed_events == 1
    assert committed_outbox == baseline_outbox + 1
    assert committed_audit == baseline_audit + 1


@pytest.mark.asyncio
async def test_c12_v2_derives_commits_idempotently_and_appends_released_state(
    postgres_runtime,
    tmp_path: Path,
) -> None:
    fixture = await build_topic4_runtime_fixture(
        postgres_runtime,
        tmp_path,
        instance_suffix="release-v2-idempotency",
    )

    with tenant_scope(fixture.context):
        _request, finalized = await finalize_release_report(fixture)
        derivation_key = "topic4-c12-v2-derive-00000000000000000001"
        derivation = _derivation_command(
            fixture,
            finalized.report.verification_id,
            idempotency_key=derivation_key,
        )
        authorization = await fixture.runtime.derive_release_authorization(
            derivation,
            idempotency_key=derivation_key,
        )
        replayed_authorization = await fixture.runtime.derive_release_authorization(
            derivation,
            idempotency_key=derivation_key,
        )
        _second_request, second_finalized = await finalize_release_report(fixture)
        with pytest.raises(ReleaseError, match="different verification"):
            await fixture.runtime.derive_release_authorization(
                _derivation_command(
                    fixture,
                    second_finalized.report.verification_id,
                    idempotency_key=derivation_key,
                ),
                idempotency_key=derivation_key,
            )

        assert authorization == replayed_authorization
        assert authorization.verification_id == finalized.report.verification_id
        assert authorization.candidate_id == fixture.candidate.candidate_id
        assert authorization.candidate_sha256 == fixture.candidate.candidate_sha256
        assert authorization.release_mode == "FULL"
        assert authorization.allowed_block_ids == [
            block.block_id for block in fixture.candidate.blocks
        ]
        assert record_integrity_valid(authorization)

        commit_key = "topic4-c12-v2-commit-00000000000000000001"
        commit = _commit_command(
            fixture,
            authorization.authorization_id,
            idempotency_key=commit_key,
        )
        first = await fixture.runtime.commit_release_v2(commit, idempotency_key=commit_key)
        second = await fixture.runtime.commit_release_v2(commit, idempotency_key=commit_key)

        async with fixture.database.transaction(context=current_session_context()) as session:
            state = await fixture.verification_repository.latest_state(
                session,
                fixture.context.tenant_id,
                finalized.report.verification_id,
            )
            consumption_count = await session.scalar(
                select(func.count())
                .select_from(Topic4ReleaseAuthorizationConsumptionModel)
                .where(
                    Topic4ReleaseAuthorizationConsumptionModel.authorization_id
                    == authorization.authorization_id
                )
            )

    assert first == second
    assert first.batch.state.value == "COMMITTED"
    assert state is not None
    assert state.change.current_state == VerificationState.RELEASED
    assert consumption_count == 1


@pytest.mark.asyncio
async def test_c12_v2_supports_full_with_disclosure_from_persisted_aggregation(
    postgres_runtime,
    tmp_path: Path,
) -> None:
    fixture = await build_topic4_runtime_fixture(
        postgres_runtime,
        tmp_path,
        instance_suffix="release-v2-disclosure",
    )
    partial_handlers = {
        module: PartiallySupportedHandler(frozenset({ClaimKind.TEXT}))
        for module in VerificationModule
    }

    with tenant_scope(fixture.context):
        _request, finalized = await finalize_release_report(
            fixture,
            handler_overrides=partial_handlers,
        )
        assert finalized.report.decision == AggregateDecision.RELEASE_WITH_DISCLOSURE
        derivation_key = "topic4-c12-v2-disclosure-derive-000000000000000001"
        requested_block_ids = [fixture.candidate.blocks[0].block_id]
        derivation = _derivation_command(
            fixture,
            finalized.report.verification_id,
            idempotency_key=derivation_key,
            requested_release_mode="FULL_WITH_DISCLOSURE",
            requested_block_ids=requested_block_ids,
        )
        authorization = await fixture.runtime.derive_release_authorization(
            derivation,
            idempotency_key=derivation_key,
        )
        assert authorization.release_mode == "FULL_WITH_DISCLOSURE"
        assert authorization.allowed_block_ids == requested_block_ids
        assert authorization.disclosure_codes

        commit_key = "topic4-c12-v2-disclosure-commit-000000000000000001"
        result = await fixture.runtime.commit_release_v2(
            _commit_command(
                fixture,
                authorization.authorization_id,
                idempotency_key=commit_key,
            ),
            idempotency_key=commit_key,
        )
        payload = await fixture.artifact_store.read(
            tenant_id=fixture.context.tenant_id,
            storage_namespace=result.public_artifact.storage_namespace,
            object_key=result.public_artifact.object_key,
            expected_byte_size=result.public_artifact.byte_size,
            expected_sha256=result.public_artifact.sha256,
        )

    assert [block["block_id"] for block in json.loads(payload)["blocks"]] == requested_block_ids
    assert result.batch.state.value == "COMMITTED"


@pytest.mark.asyncio
async def test_c12_v2_rejects_changed_commit_replay_and_cross_tenant_derivation(
    postgres_runtime,
    tmp_path: Path,
) -> None:
    fixture = await build_topic4_runtime_fixture(
        postgres_runtime,
        tmp_path,
        instance_suffix="release-v2-boundary",
    )
    foreign_context = await _provision_foreign_tenant(fixture)

    with tenant_scope(fixture.context):
        _request, finalized = await finalize_release_report(fixture)
        derivation_key = "topic4-c12-v2-boundary-derive-00000000000000000001"
        derivation = _derivation_command(
            fixture,
            finalized.report.verification_id,
            idempotency_key=derivation_key,
        )
        authorization = await fixture.runtime.derive_release_authorization(
            derivation,
            idempotency_key=derivation_key,
        )
        commit_key = "topic4-c12-v2-boundary-commit-00000000000000000001"
        commit = _commit_command(
            fixture,
            authorization.authorization_id,
            idempotency_key=commit_key,
        )
        published = await fixture.runtime.commit_release_v2(commit, idempotency_key=commit_key)
        changed_commit_key = "topic4-c12-v2-boundary-commit-00000000000000000002"
        changed_commit = _commit_command(
            fixture,
            authorization.authorization_id,
            idempotency_key=changed_commit_key,
        )
        with pytest.raises(AuthorizationReplayError):
            await fixture.runtime.commit_release_v2(
                changed_commit,
                idempotency_key=changed_commit_key,
            )

    with tenant_scope(foreign_context):
        with pytest.raises(ReleaseError, match="trusted context"):
            await fixture.runtime.derive_release_authorization(
                derivation,
                idempotency_key=derivation_key,
            )
        with pytest.raises(ReleaseError, match="trusted context"):
            await fixture.runtime.commit_release_v2(
                commit,
                idempotency_key=commit_key,
            )

    assert published.batch.state.value == "COMMITTED"
