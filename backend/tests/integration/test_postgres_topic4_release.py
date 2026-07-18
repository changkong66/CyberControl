from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from liyans.core.tenant import TenantContext, TenantIsolationError, tenant_scope
from liyans.domains.release.engine import (
    AuthorizationExpiredError,
    AuthorizationReplayError,
    C12ReleaseService,
    PublicationIntegrityError,
)
from liyans.domains.release.postgres_repository import PostgresAtomicReleaseRepository
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
