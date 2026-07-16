from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c1 import (
    PublicationBatchV1,
    PublicationState,
    PublicStreamEventV1,
    VerificationReportV1,
)
from liyans_contracts.topic4_common import AggregateDecision
from liyans_contracts.verification import ReleaseAuthorizationPayloadV1
from test_topic4_control_plane import NOW, TENANT_ID, TRACE_ID, _candidate

from liyans.core.tenant import TenantContext, TenantIsolationError, tenant_scope
from liyans.domains.release import (
    AuthorizationConflictError,
    AuthorizationExpiredError,
    AuthorizationReplayError,
    C12ReleaseService,
    InMemoryAtomicReleaseRepository,
    PostgresAtomicReleaseRepository,
    PublicationIntegrityError,
    PublicationRequest,
)
from liyans.domains.verification.records import build_topic4_record, record_integrity_valid
from liyans.infrastructure.persistence.artifacts import StoredArtifactObject
from liyans.infrastructure.persistence.filesystem_artifacts import FileSystemArtifactObjectStore

TENANT = TENANT_ID
SUBJECT = "subject:c12-test"


def _context(tenant_id: str = TENANT) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        subject_ref=SUBJECT,
        roles=frozenset({"teacher"}),
        scopes=frozenset({"topic4:release"}),
        trace_id=TRACE_ID,
    )


def _artifact(sha256: str, key: str, *, size: int = 1) -> ArtifactObjectRefV1:
    return ArtifactObjectRefV1(
        schema_version="artifact.object.ref.v1",
        storage_namespace="verification-artifacts",
        object_key=key,
        media_type="application/json",
        content_encoding="identity",
        byte_size=size,
        sha256=sha256,
        created_at=NOW,
    )


def _report(
    candidate, *, decision: AggregateDecision = AggregateDecision.RELEASE
) -> VerificationReportV1:
    report_id = uuid4()
    report_document = {
        "report_id": str(report_id),
        "candidate_id": str(candidate.candidate_id),
        "decision": decision.value,
    }
    report_sha256 = canonical_sha256(report_document)
    return build_topic4_record(
        VerificationReportV1,
        trace_id=TRACE_ID,
        tenant_id=TENANT,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="verification.report.v1",
        report_id=report_id,
        verification_id=uuid4(),
        candidate_id=candidate.candidate_id,
        candidate_version=candidate.candidate_version,
        candidate_sha256=candidate.candidate_sha256,
        knowledge_base_version="topic1.knowledge.v1",
        aggregation_result_id=uuid4(),
        decision=decision,
        claim_verdict_ids=[uuid4()],
        evidence_chain_manifest_id=uuid4(),
        report_artifact=_artifact(report_sha256, "c12/reports/report.json", size=128),
        report_sha256=report_sha256,
        policy_version="topic4.release-policy.v1",
        completed_at=NOW,
    )


def _authorization(
    candidate,
    report: VerificationReportV1,
    *,
    release_mode: str = "FULL",
    allowed_block_ids: list[str] | None = None,
    disclosure_codes: list[str] | None = None,
    issued_at: datetime = NOW,
    expires_at: datetime | None = None,
) -> ReleaseAuthorizationPayloadV1:
    return build_topic4_record(
        ReleaseAuthorizationPayloadV1,
        trace_id=TRACE_ID,
        tenant_id=TENANT,
        version_cas=1,
        created_at=issued_at,
        immutable=True,
        schema_version="release.authorization.v1",
        authorization_id=uuid4(),
        verification_id=report.verification_id,
        report_id=report.report_id,
        candidate_id=candidate.candidate_id,
        candidate_version=candidate.candidate_version,
        candidate_sha256=candidate.candidate_sha256,
        release_mode=release_mode,
        allowed_block_ids=allowed_block_ids or [block.block_id for block in candidate.blocks],
        disclosure_codes=disclosure_codes or [],
        report_sha256=report.report_sha256,
        issued_at=issued_at,
        expires_at=expires_at or issued_at + timedelta(hours=1),
        one_time_use=True,
    )


def _request(
    authorization: ReleaseAuthorizationPayloadV1,
    report: VerificationReportV1,
    candidate,
) -> PublicationRequest:
    document = {
        "authorization_id": str(authorization.authorization_id),
        "verification_id": str(authorization.verification_id),
        "report_id": str(authorization.report_id),
        "candidate_id": str(authorization.candidate_id),
        "candidate_version": authorization.candidate_version,
        "candidate_sha256": authorization.candidate_sha256,
        "report_sha256": authorization.report_sha256,
        "allowed_block_ids": authorization.allowed_block_ids,
    }
    return PublicationRequest(
        authorization=authorization,
        report=report,
        candidate=candidate,
        request_document=document,
        request_sha256=canonical_sha256(document),
        subject_ref=SUBJECT,
    )


async def _service(tmp_path: Path, *, clock=NOW):
    repository = InMemoryAtomicReleaseRepository(clock=lambda: clock)
    store = FileSystemArtifactObjectStore(tmp_path)
    return C12ReleaseService(repository, store), repository, store


@pytest.mark.asyncio
async def test_c12_full_release_is_atomic_and_idempotent(tmp_path: Path) -> None:
    candidate = _candidate()
    report = _report(candidate)
    authorization = _authorization(candidate, report)
    request = _request(authorization, report, candidate)
    service, _, store = await _service(tmp_path)

    with tenant_scope(_context()):
        await service.issue_authorization(authorization, now=NOW)
        first = await service.publish(request, now=NOW)
        second = await service.publish(request, now=NOW)

    assert first == second
    assert first.batch.state.value == "COMMITTED"
    assert first.batch.public_artifacts == [first.public_artifact]
    assert first.public_event.payload_sha256 == first.public_event.payload_artifact.sha256
    assert record_integrity_valid(first.batch)
    assert record_integrity_valid(first.public_event)
    payload = await store.read(
        tenant_id=TENANT,
        storage_namespace=first.public_artifact.storage_namespace,
        object_key=first.public_artifact.object_key,
        expected_byte_size=first.public_artifact.byte_size,
        expected_sha256=first.public_artifact.sha256,
    )
    assert len(json.loads(payload)["blocks"]) == len(candidate.blocks)


@pytest.mark.asyncio
async def test_c12_disclosure_release_only_publishes_authorized_blocks(tmp_path: Path) -> None:
    candidate = _candidate()
    report = _report(candidate, decision=AggregateDecision.RELEASE_WITH_DISCLOSURE)
    allowed = [candidate.blocks[0].block_id, candidate.blocks[2].block_id]
    authorization = _authorization(
        candidate,
        report,
        release_mode="FULL_WITH_DISCLOSURE",
        allowed_block_ids=allowed,
        disclosure_codes=["C12_DISCLOSURE"],
    )
    service, _, store = await _service(tmp_path)

    with tenant_scope(_context()):
        await service.issue_authorization(authorization, now=NOW)
        result = await service.publish(_request(authorization, report, candidate), now=NOW)

    payload = await store.read(
        tenant_id=TENANT,
        storage_namespace=result.public_artifact.storage_namespace,
        object_key=result.public_artifact.object_key,
        expected_byte_size=result.public_artifact.byte_size,
        expected_sha256=result.public_artifact.sha256,
    )
    assert [block["block_id"] for block in json.loads(payload)["blocks"]] == allowed


@pytest.mark.asyncio
async def test_c12_rejects_expired_authorization_and_invalid_block(tmp_path: Path) -> None:
    candidate = _candidate()
    report = _report(candidate)
    expired_at = NOW - timedelta(seconds=1)
    authorization = _authorization(
        candidate,
        report,
        issued_at=NOW - timedelta(hours=2),
        expires_at=expired_at,
    )
    service, _, _ = await _service(tmp_path)

    with tenant_scope(_context()):
        await service.issue_authorization(authorization, now=NOW - timedelta(hours=2))
        with pytest.raises(AuthorizationExpiredError):
            await service.publish(_request(authorization, report, candidate), now=NOW)

    invalid = _authorization(
        candidate,
        report,
        allowed_block_ids=["missing-block"],
    )
    invalid_service, _, _ = await _service(tmp_path / "invalid")
    with tenant_scope(_context()):
        await invalid_service.issue_authorization(invalid, now=NOW)
        with pytest.raises(PublicationIntegrityError, match="invalid block"):
            await invalid_service.publish(_request(invalid, report, candidate), now=NOW)


@pytest.mark.asyncio
async def test_c12_rejects_record_hash_tampering_and_cross_tenant_access(tmp_path: Path) -> None:
    candidate = _candidate()
    report = _report(candidate)
    authorization = _authorization(candidate, report)
    service, _, _ = await _service(tmp_path)

    with tenant_scope(_context()):
        await service.issue_authorization(authorization, now=NOW)
        tampered_report = report.model_copy(update={"report_sha256": "f" * 64})
        with pytest.raises(PublicationIntegrityError, match="report record SHA"):
            await service.publish(_request(authorization, tampered_report, candidate), now=NOW)

    with tenant_scope(_context("foreign-tenant")):
        with pytest.raises(TenantIsolationError):
            await service.publish(_request(authorization, report, candidate), now=NOW)


@pytest.mark.asyncio
async def test_c12_rejects_changed_replay_request(tmp_path: Path) -> None:
    candidate = _candidate()
    report = _report(candidate)
    authorization = _authorization(candidate, report)
    request = _request(authorization, report, candidate)
    service, repository, _ = await _service(tmp_path)

    with tenant_scope(_context()):
        await service.issue_authorization(authorization, now=NOW)
        first = await service.publish(request, now=NOW)
        changed = replace(request, request_sha256="f" * 64)
        with pytest.raises(AuthorizationReplayError):
            await repository.consume_and_publish(
                changed, first.public_artifact, first.public_event.payload_artifact
            )


@pytest.mark.asyncio
async def test_c12_rejects_issued_authorization_payload_mismatch(tmp_path: Path) -> None:
    candidate = _candidate()
    report = _report(candidate)
    authorization = _authorization(candidate, report)
    service, repository, _ = await _service(tmp_path)
    altered = build_topic4_record(
        ReleaseAuthorizationPayloadV1,
        **{
            **authorization.model_dump(
                mode="python", exclude={"record_sha256", "candidate_sha256"}
            ),
            "candidate_sha256": "e" * 64,
        },
    )

    with tenant_scope(_context()):
        await service.issue_authorization(authorization, now=NOW)
        request = _request(altered, report, candidate)
        with pytest.raises(AuthorizationConflictError, match="issued record"):
            await repository.consume_and_publish(
                request,
                _artifact("a" * 64, "c12/public.json"),
                _artifact("b" * 64, "c12/event.json"),
            )


class _CorruptStore:
    async def put(self, *, tenant_id, storage_namespace, object_key, content):
        return StoredArtifactObject(
            tenant_id=tenant_id,
            storage_namespace=storage_namespace,
            object_key=object_key,
            byte_size=len(content),
            sha256="0" * 64,
            created=False,
        )


class _Result:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value


class _FakeSession:
    def __init__(self, results: list[_Result]) -> None:
        self._results = list(results)
        self.added: list[object] = []

    async def execute(self, _statement, _parameters=None):
        return self._results.pop(0)

    async def flush(self) -> None:
        return None

    def add(self, value) -> None:
        self.added.append(value)


class _FakeDatabase:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def run_transaction(self, operation, **_kwargs):
        return await operation(self.session)


class _FakeOutbox:
    def __init__(self) -> None:
        self.messages = []

    async def append(self, _session, message) -> None:
        self.messages.append(message)


def _authorization_row(authorization: ReleaseAuthorizationPayloadV1):
    return SimpleNamespace(
        tenant_id=authorization.tenant_id,
        authorization_id=authorization.authorization_id,
        verification_id=authorization.verification_id,
        report_id=authorization.report_id,
        candidate_id=authorization.candidate_id,
        candidate_version=authorization.candidate_version,
        candidate_sha256=authorization.candidate_sha256,
        report_sha256=authorization.report_sha256,
        release_mode=authorization.release_mode,
        allowed_block_ids=authorization.allowed_block_ids,
        issued_at=authorization.issued_at,
        expires_at=authorization.expires_at,
        one_time_use=True,
        trace_id=authorization.trace_id,
        version_cas=authorization.version_cas,
        record_sha256=authorization.record_sha256,
        authorization_document=authorization.model_dump(mode="json"),
    )


@pytest.mark.asyncio
async def test_c12_postgres_adapter_runs_serializable_publish_and_outbox_atomically() -> None:
    candidate = _candidate()
    report = _report(candidate)
    authorization = _authorization(candidate, report)
    request = _request(authorization, report, candidate)
    issue_session = _FakeSession([_Result(None), _Result(None), _Result(None), _Result(None)])
    outbox = _FakeOutbox()
    repository = PostgresAtomicReleaseRepository(
        _FakeDatabase(issue_session), outbox, clock=lambda: NOW
    )

    with tenant_scope(_context()):
        await repository.issue_authorization(authorization, authorization.model_dump(mode="json"))

    consume_session = _FakeSession(
        [
            _Result(_authorization_row(authorization)),
            _Result(None),
            _Result(None),
            _Result(None),
            _Result(None),
            _Result(0),
        ]
    )
    repository = PostgresAtomicReleaseRepository(
        _FakeDatabase(consume_session), outbox, clock=lambda: NOW
    )
    public_artifact = _artifact("a" * 64, "c12/public.json")
    event_artifact = _artifact("b" * 64, "c12/event.json")

    with tenant_scope(_context()):
        result = await repository.consume_and_publish(request, public_artifact, event_artifact)

    assert result.batch.state.value == "COMMITTED"
    assert result.batch.version_cas == 2
    assert record_integrity_valid(result.batch)
    assert record_integrity_valid(result.public_event)
    assert len(outbox.messages) == 1
    assert len(consume_session.added) >= 5


@pytest.mark.asyncio
async def test_c12_postgres_replay_requires_complete_immutable_snapshots() -> None:
    candidate = _candidate()
    report = _report(candidate)
    authorization = _authorization(candidate, report)
    outbox = _FakeOutbox()
    repository = PostgresAtomicReleaseRepository(
        _FakeDatabase(_FakeSession([])), outbox, clock=lambda: NOW
    )
    batch = build_topic4_record(
        PublicationBatchV1,
        trace_id=TRACE_ID,
        tenant_id=TENANT,
        version_cas=2,
        created_at=NOW,
        immutable=True,
        schema_version="publication-batch.v1",
        publication_batch_id=uuid4(),
        authorization_id=authorization.authorization_id,
        verification_id=authorization.verification_id,
        report_id=authorization.report_id,
        candidate_id=candidate.candidate_id,
        candidate_version=candidate.candidate_version,
        candidate_sha256=candidate.candidate_sha256,
        state=PublicationState.COMMITTED,
        public_artifacts=[_artifact("a" * 64, "c12/public.json")],
        outbox_event_ids=[uuid4()],
        public_stream_event_ids=[uuid4()],
        committed_at=NOW,
    )
    event = build_topic4_record(
        PublicStreamEventV1,
        trace_id=TRACE_ID,
        tenant_id=TENANT,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="public.stream.event.v1",
        public_event_id=uuid4(),
        publication_batch_id=batch.publication_batch_id,
        authorization_id=authorization.authorization_id,
        stream_id=uuid4(),
        sequence=0,
        event_type="topic4.publication.committed",
        payload_artifact=_artifact("b" * 64, "c12/event.json"),
        payload_sha256="b" * 64,
        emitted_at=NOW,
    )
    batch_row = SimpleNamespace(
        tenant_id=TENANT,
        publication_batch_id=batch.publication_batch_id,
        batch_version=2,
        record_sha256=batch.record_sha256,
        batch_document=batch.model_dump(mode="json"),
    )
    event_row = SimpleNamespace(
        tenant_id=TENANT,
        publication_batch_id=batch.publication_batch_id,
        public_event_id=event.public_event_id,
        record_sha256=event.record_sha256,
        payload_sha256=event.payload_sha256,
        event_document=event.model_dump(mode="json"),
    )
    session = _FakeSession([_Result(batch_row), _Result(event_row)])

    with tenant_scope(_context()):
        replay = await repository._replay(session, _context(), batch.publication_batch_id)

    assert replay.batch == batch
    assert replay.public_event == event
    assert replay.public_artifact == batch.public_artifacts[0]

    broken_data = vars(batch_row).copy()
    broken_data["record_sha256"] = "0" * 64
    broken_row = SimpleNamespace(**broken_data)
    with pytest.raises(PublicationIntegrityError, match="batch integrity"):
        await repository._replay(
            _FakeSession([_Result(broken_row)]), _context(), batch.publication_batch_id
        )


def test_c12_postgres_authorization_row_mismatch_fails_closed() -> None:
    candidate = _candidate()
    report = _report(candidate)
    authorization = _authorization(candidate, report)
    altered_data = vars(_authorization_row(authorization)).copy()
    altered_data["candidate_version"] = 99
    altered = SimpleNamespace(**altered_data)

    with pytest.raises(PublicationIntegrityError, match="authorization row"):
        PostgresAtomicReleaseRepository._assert_authorization_row_matches(altered, authorization)


@pytest.mark.asyncio
async def test_c12_fails_closed_when_object_store_metadata_is_corrupt(tmp_path: Path) -> None:
    candidate = _candidate()
    report = _report(candidate)
    authorization = _authorization(candidate, report)
    service = C12ReleaseService(InMemoryAtomicReleaseRepository(clock=lambda: NOW), _CorruptStore())

    with tenant_scope(_context()):
        await service.issue_authorization(authorization, now=NOW)
        with pytest.raises(PublicationIntegrityError, match="artifact store"):
            await service.publish(_request(authorization, report, candidate), now=NOW)


def test_c12_contract_records_have_canonical_hashes() -> None:
    event = build_topic4_record(
        PublicStreamEventV1,
        trace_id=TRACE_ID,
        tenant_id=TENANT,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="public.stream.event.v1",
        public_event_id=uuid4(),
        publication_batch_id=uuid4(),
        authorization_id=uuid4(),
        stream_id=uuid4(),
        sequence=0,
        event_type="topic4.publication.committed",
        payload_artifact=_artifact("a" * 64, "c12/event.json"),
        payload_sha256="a" * 64,
        emitted_at=NOW,
    )
    assert record_integrity_valid(event)
