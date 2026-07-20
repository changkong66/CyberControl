from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from integration.test_postgres_topic4 import _verification_request
from liyans_contracts.topic4_c1 import ClaimV1, ReviewTaskState
from liyans_contracts.topic4_c11 import ComplianceBuildProvenanceInputV1
from test_topic4_c12_release import _authorization, _report
from test_topic4_control_plane import TENANT_ID, TRACE_ID, _candidate

from liyans.api.routes.topic4 import RevisionCommand, create_revision, stream_public_events
from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.domains.release.engine import ReleaseError
from liyans.domains.verification.claim_extraction import DeterministicClaimExtractor
from liyans.domains.verification.runtime import (
    TOPIC4_INTERNAL_OUTBOX_EVENT_TYPES,
    map_topic4_error,
)
from liyans.infrastructure.security import AuthenticatedPrincipal
from liyans.infrastructure.streaming.sse import (
    InMemorySSEReplayLog,
    ReplayCursorCodec,
    SSEBroker,
    SSEEvent,
)
from liyans.main import create_app


def test_topic4_internal_outbox_events_have_a_durable_runtime_sink() -> None:
    assert set(TOPIC4_INTERNAL_OUTBOX_EVENT_TYPES) == {
        "topic4.knowledge.source_imported",
        "topic4.knowledge.base_activated",
        "topic4.knowledge.retrieval_completed",
        "topic4.knowledge.index_self_healed",
        "topic4.verification.accepted",
        "topic4.verification.state_changed",
        "topic4.verification.control_plane_prepared",
        "topic4.verification.modules_recorded",
        "topic4.verification.aggregated",
        "topic4.verification.human_review_decided",
    }
    assert "topic4.publication.committed" not in TOPIC4_INTERNAL_OUTBOX_EVENT_TYPES


class _StreamBroker:
    def __init__(self, events: list[SSEEvent | None]) -> None:
        self.events = events
        self.after_sequence: int | None = None

    async def subscribe(self, _tenant_id: str, *, after_sequence: int | None = None):
        self.after_sequence = after_sequence
        for event in self.events:
            yield event


class _StreamRequest:
    def __init__(self, broker: _StreamBroker, *, disconnected: bool = False) -> None:
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                sse_broker=broker,
                sse_cursor_codec=ReplayCursorCodec(b"topic4-api-test-cursor-secret-32-bytes"),
            )
        )
        self._disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self._disconnected


@pytest.mark.asyncio
async def test_topic4_sse_stream_restores_cursor_filters_and_heartbeats() -> None:
    broker = _StreamBroker(
        [
            None,
            SSEEvent(TENANT_ID, 5, "topic3.internal", {"ignored": True}, datetime.now(UTC)),
            SSEEvent(
                TENANT_ID,
                6,
                "topic4.publication.committed",
                {"authorization_id": "authorization-1"},
                datetime.now(UTC),
            ),
        ]
    )
    request = _StreamRequest(broker)
    context = TenantContext(
        tenant_id=TENANT_ID,
        subject_ref="subject:topic4-api",
        roles=frozenset(),
        scopes=frozenset({"topic4:sse:read"}),
        trace_id=TRACE_ID,
    )
    cursor = request.app.state.sse_cursor_codec.encode(TENANT_ID, 4)

    with tenant_scope(context):
        response = await stream_public_events(request, cursor)  # type: ignore[arg-type]
        body = b"".join([chunk async for chunk in response.body_iterator])

    assert broker.after_sequence == 4
    assert b": heartbeat\n\n" in body
    assert b"event: topic4.publication.committed" in body
    assert b"authorization-1" in body
    assert b"topic3.internal" not in body
    assert response.headers["x-accel-buffering"] == "no"


@pytest.mark.asyncio
async def test_topic4_sse_stream_stops_when_client_disconnects() -> None:
    broker = _StreamBroker([SSEEvent(TENANT_ID, 0, "topic4.test", {"ok": True}, datetime.now(UTC))])
    request = _StreamRequest(broker, disconnected=True)
    context = TenantContext(
        tenant_id=TENANT_ID,
        subject_ref="subject:topic4-api",
        roles=frozenset(),
        scopes=frozenset({"topic4:sse:read"}),
        trace_id=TRACE_ID,
    )

    with tenant_scope(context):
        response = await stream_public_events(request, None)  # type: ignore[arg-type]
        body = b"".join([chunk async for chunk in response.body_iterator])

    assert body == b""
    assert broker.after_sequence is None


class _Document:
    def __init__(self, document: dict) -> None:
        self._document = document

    def model_dump(self, *, mode: str = "python") -> dict:
        del mode
        return dict(self._document)


class _StubTopic4Runtime:
    def __init__(self, candidate, report, claim: ClaimV1) -> None:
        self.ready = True
        self.candidate = candidate
        self.report = report
        self.claim = claim
        self.enqueued: list[UUID] = []
        self.authorization = None
        self.review_task = _Document(
            {
                "review_task_id": str(uuid4()),
                "verification_id": str(report.verification_id),
                "state": "OPEN",
            }
        )
        self.review_decision = _Document(
            {
                "review_decision_id": str(uuid4()),
                "verification_id": str(report.verification_id),
                "decision": "REVISE",
            }
        )
        self.compliance_package_document = _Document(
            {
                "compliance_evidence_package_id": str(uuid4()),
                "verification_id": str(report.verification_id),
                "claim_id": str(claim.claim_id),
                "state": "IMPORTED",
            }
        )

    async def accept(self, request):
        return {
            "accepted": {
                "verification_id": str(request.verification_id),
                "state": "ACCEPTED",
            },
            "dispatch_mode": "LOCAL_QUEUE",
        }

    async def enqueue(self, verification_id: UUID) -> None:
        self.enqueued.append(verification_id)

    async def snapshot(self, verification_id: UUID) -> dict:
        return {
            "verification": {"verification_id": str(verification_id)},
            "state": {"current_state": "RELEASE_PENDING"},
            "claims": [self.claim.model_dump(mode="json")],
            "risks": [],
            "dispatch_plan": None,
            "module_runs": [],
            "module_results": [],
            "claim_verdicts": [],
            "aggregation": None,
            "report": self.report.model_dump(mode="json"),
            "review_task": None,
        }

    async def claims(self, _verification_id: UUID):
        return [self.claim]

    async def retrieve(self, claim: ClaimV1, **_kwargs):
        return _Document(
            {
                "verification_id": str(claim.verification_id),
                "claim_id": str(claim.claim_id),
                "status": "SUCCEEDED",
            }
        )

    async def evidence(self, _claim_id: UUID):
        return [_Document({"evidence_ref_id": str(uuid4()), "score": 0.98})]

    async def revisions(self, verification_id: UUID, *, limit: int):
        return [{"verification_id": str(verification_id), "limit": limit}]

    async def revision(self, request, _patches, *, prompt_bundle_version: str):
        return SimpleNamespace(
            cycle=_Document({"verification_id": str(request.verification_id)}),
            plan=_Document({"prompt_bundle_version": prompt_bundle_version}),
            patches=(_Document({"operation": "REPLACE_BLOCK"}),),
            candidate=SimpleNamespace(candidate=self.candidate),
            response=_Document({"state": "COMPLETED"}),
            reverification=SimpleNamespace(
                as_document=lambda: {
                    "verification_id": str(uuid4()),
                    "parent_verification_id": str(request.verification_id),
                }
            ),
        )

    async def issue_authorization(self, authorization):
        self.authorization = authorization
        return authorization

    async def validate_authorization(self, authorization):
        if self.authorization is not None and (
            authorization.authorization_id != self.authorization.authorization_id
        ):
            raise ReleaseError("unknown authorization")

    async def import_compliance(self, _command):
        return self.compliance_package_document

    async def compliance_package(self, _verification_id: UUID | None, _claim_id: UUID):
        return self.compliance_package_document

    async def derive_release_authorization(self, _command, *, idempotency_key: str):
        del idempotency_key
        if self.authorization is None:
            raise ReleaseError("missing authorization fixture")
        return self.authorization

    async def commit_release_v2(self, _command, *, idempotency_key: str):
        del idempotency_key
        if self.authorization is None:
            raise ReleaseError("missing authorization fixture")
        return await self.publish(SimpleNamespace(authorization=self.authorization))

    async def review_tasks(self, _state: ReviewTaskState):
        return [self.review_task]

    async def submit_review(self, **_kwargs):
        return SimpleNamespace(
            decision=self.review_decision,
            review_task=self.review_task,
            state=_Document({"current_state": "REVISION_PLANNING"}),
        )

    async def publish(self, publication_request):
        return SimpleNamespace(
            batch=_Document(
                {
                    "publication_batch_id": str(uuid4()),
                    "authorization_id": str(publication_request.authorization.authorization_id),
                    "state": "COMMITTED",
                }
            ),
            public_event=_Document(
                {
                    "event_type": "topic4.publication.committed",
                    "authorization_id": str(publication_request.authorization.authorization_id),
                }
            ),
            public_artifact=_Document(
                {
                    "storage_namespace": "verification-artifacts",
                    "object_key": "topic4/public/test.json",
                    "sha256": "a" * 64,
                }
            ),
        )

    async def trace(self, trace_id: str, *, limit: int):
        return {
            "trace_id": trace_id,
            "tenant_id": TENANT_ID,
            "record_count": 1,
            "records": [{"table": "topic4_verifications", "limit": limit}],
        }

    async def publication_history(self, *, verification_id: UUID | None, limit: int):
        return [
            {
                "table": "topic4_publication_batches",
                "verification_id": None if verification_id is None else str(verification_id),
                "limit": limit,
            }
        ]


class _TokenVerifier:
    def __init__(self, scopes: frozenset[str]) -> None:
        self._scopes = scopes

    async def verify(self, token: str) -> AuthenticatedPrincipal:
        assert token == "topic4-token"
        now = datetime.now(UTC)
        return AuthenticatedPrincipal(
            issuer="https://issuer.test",
            subject="subject:topic4-api",
            tenant_id=TENANT_ID,
            roles=frozenset({"teacher"}),
            scopes=self._scopes,
            token_id="topic4-api-jti",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )


class _TenantAuthorizer:
    async def authorize(
        self,
        principal: AuthenticatedPrincipal,
        *,
        trace_id: str,
    ) -> TenantContext:
        return TenantContext(
            tenant_id=principal.tenant_id,
            subject_ref=principal.subject,
            roles=principal.roles,
            scopes=principal.scopes,
            trace_id=trace_id,
        )


def _install_runtime(
    app,
    runtime: _StubTopic4Runtime,
    *,
    scopes: frozenset[str] | None = None,
) -> None:
    scopes = scopes or frozenset(
        {
            "topic4:read",
            "topic4:verification:write",
            "topic4:verification:execute",
            "topic4:verification:read",
            "topic4:claim:read",
            "topic4:trace:read",
            "topic4:report:read",
            "topic4:rag:read",
            "topic4:revision:read",
            "topic4:release:read",
            "topic4:release:write",
            "topic4:sse:read",
            "topic4:review:read",
            "topic4:review:write",
            "topic4:compliance:read",
            "topic4:compliance:write",
        }
    )
    app.state.token_verifier = _TokenVerifier(scopes)
    app.state.tenant_authorizer = _TenantAuthorizer()
    app.state.auth_configured = True
    app.state.topic4_runtime = runtime
    replay_log = InMemorySSEReplayLog(capacity_per_tenant=100)
    app.state.sse_replay_log = replay_log
    app.state.sse_broker = SSEBroker(replay_log)
    app.state.sse_cursor_codec = ReplayCursorCodec(b"topic4-api-test-cursor-secret-32-bytes")


@pytest.mark.asyncio
async def test_topic4_api_exposes_runtime_release_and_replay_contracts() -> None:
    candidate = _candidate()
    report = _report(candidate)
    issued_at = datetime.now(UTC)
    authorization = _authorization(
        candidate,
        report,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=5),
    )
    claim = DeterministicClaimExtractor().extract(
        candidate,
        verification_id=report.verification_id,
        trace_id=TRACE_ID,
        tenant_id=TENANT_ID,
        created_at=datetime.now(UTC),
    )[0]
    runtime = _StubTopic4Runtime(candidate, report, claim)
    app = create_app()
    _install_runtime(app, runtime)
    request_payload = _verification_request(
        candidate,
        tenant_id=TENANT_ID,
        now=datetime.now(UTC),
    )
    headers = {
        "authorization": "Bearer topic4-token",
        "x-trace-id": TRACE_ID,
    }
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        health = await client.get("/internal/topic4/health", headers=headers)
        created = await client.post(
            "/internal/topic4/verifications",
            headers=headers,
            json=request_payload.model_dump(mode="json"),
        )
        executed = await client.post(
            f"/internal/topic4/verifications/{request_payload.verification_id}/execute",
            headers=headers,
        )
        batch = await client.post(
            "/internal/topic4/verifications/batch",
            headers=headers,
            json={"verification_ids": [str(request_payload.verification_id)]},
        )
        verification = await client.get(
            f"/internal/topic4/verifications/{request_payload.verification_id}",
            headers=headers,
        )
        claims = await client.get(
            f"/internal/topic4/verifications/{request_payload.verification_id}/claims",
            headers=headers,
        )
        trace = await client.get(f"/internal/topic4/traces/{TRACE_ID}?limit=25", headers=headers)
        report_response = await client.get(
            f"/internal/topic4/verifications/{request_payload.verification_id}/report",
            headers=headers,
        )
        retrieval = await client.post(
            "/internal/topic4/rag/retrieve",
            headers={**headers, "Idempotency-Key": "topic4-api-rag-00000000000000000001"},
            json={"claim": claim.model_dump(mode="json"), "course_id": "CRS-ATC"},
        )
        compliance_provenance = ComplianceBuildProvenanceInputV1(
            builder_id="liyans-local-python-evidence",
            builder_version="1.0.0",
            toolchain_manifest_version="topic4-toolchain-v1",
            source_sha256="a" * 64,
            build_output_document={"status": "verified"},
            sandbox_policy_id=uuid4(),
            reproducible=True,
            build_command_sha256="b" * 64,
        )
        compliance = await client.post(
            "/internal/topic4/compliance/packages",
            headers={
                **headers,
                "Idempotency-Key": "topic4-api-compliance-000000000000000001",
            },
            json={
                "verification_id": str(claim.verification_id),
                "claim_id": str(claim.claim_id),
                "sbom_document": {
                    "bomFormat": "CycloneDX",
                    "specVersion": "1.5",
                    "serialNumber": "urn:uuid:topic4-api",
                    "components": [],
                },
                "vulnerability_records": [],
                "provenance_document": compliance_provenance.model_dump(mode="json"),
            },
        )
        compliance_read = await client.get(
            f"/internal/topic4/compliance/claims/{claim.claim_id}",
            headers=headers,
        )
        evidence = await client.get(
            f"/internal/topic4/claims/{claim.claim_id}/evidence",
            headers=headers,
        )
        revisions = await client.get(
            f"/internal/topic4/verifications/{request_payload.verification_id}/revisions?limit=10",
            headers=headers,
        )
        valid = await client.post(
            "/internal/topic4/release/authorizations/validate",
            headers=headers,
            json=authorization.model_dump(mode="json"),
        )
        issued = await client.post(
            "/internal/topic4/release/authorizations",
            headers=headers,
            json=authorization.model_dump(mode="json"),
        )
        derived = await client.post(
            "/internal/topic4/release/authorizations/derive",
            headers={
                **headers,
                "Idempotency-Key": "topic4-api-derive-00000000000000000001",
            },
            json={
                "verification_id": str(report.verification_id),
                "requested_release_mode": "FULL",
                "requested_block_ids": [],
                "ttl_seconds": 120,
            },
        )
        publication_body = {
            "authorization": authorization.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
        }
        published = await client.post(
            "/internal/topic4/release/publications",
            headers=headers,
            json=publication_body,
        )
        committed_v2 = await client.post(
            "/internal/topic4/release/publications/commit",
            headers={
                **headers,
                "Idempotency-Key": "topic4-api-commit-00000000000000000001",
            },
            json={"authorization_id": str(authorization.authorization_id)},
        )
        published_batch = await client.post(
            "/internal/topic4/release/publications/batch",
            headers=headers,
            json={"publications": [publication_body, publication_body]},
        )
        history = await client.get(
            f"/internal/topic4/release/history?verification_id={report.verification_id}&limit=20",
            headers=headers,
        )
        review_tasks = await client.get(
            "/internal/topic4/reviews/tasks?state=OPEN",
            headers=headers,
        )
        review_decision = await client.post(
            f"/internal/topic4/verifications/{report.verification_id}/reviews/decisions",
            headers={
                **headers,
                "Idempotency-Key": "topic4-api-review-00000000000000000001",
            },
            json={
                "review_task_id": runtime.review_task._document["review_task_id"],
                "decision": "REVISE",
                "rationale": "The persisted finding requires a revision.",
                "disclosure_codes": [],
                "waived_finding_ids": [],
                "expected_task_version": 1,
                "expected_state_version": 1,
            },
        )
        await app.state.sse_broker.publish(
            TENANT_ID,
            "topic4.publication.committed",
            {"authorization_id": str(authorization.authorization_id)},
        )
        replay = await client.get("/internal/topic4/sse/replay?after_sequence=-1", headers=headers)

    responses = (
        health,
        created,
        executed,
        batch,
        verification,
        claims,
        trace,
        report_response,
        retrieval,
        compliance,
        compliance_read,
        evidence,
        revisions,
        valid,
        issued,
        derived,
        published,
        committed_v2,
        published_batch,
        history,
        review_tasks,
        review_decision,
        replay,
    )
    assert all(response.status_code < 300 for response in responses), [
        (response.status_code, response.text) for response in responses
    ]
    assert batch.json()["payload"]["verifications"][0]["verification"]["verification_id"] == str(
        request_payload.verification_id
    )
    assert runtime.enqueued == [request_payload.verification_id]
    assert review_tasks.json()["payload"]["tasks"][0]["state"] == "OPEN"
    assert review_decision.json()["payload"]["decision"]["decision"] == "REVISE"
    assert compliance.json()["payload"]["package"]["state"] == "IMPORTED"
    assert compliance_read.json()["payload"]["package"]["state"] == "IMPORTED"
    assert derived.json()["payload"]["authorization"]["authorization_id"] == str(
        authorization.authorization_id
    )
    assert committed_v2.json()["payload"]["state"] == "RELEASED"
    assert replay.json()["payload"]["events"][0]["event_type"] == ("topic4.publication.committed")


@pytest.mark.asyncio
async def test_topic4_review_routes_enforce_scope() -> None:
    candidate = _candidate()
    report = _report(candidate)
    claim = DeterministicClaimExtractor().extract(
        candidate,
        verification_id=report.verification_id,
        trace_id=TRACE_ID,
        tenant_id=TENANT_ID,
        created_at=datetime.now(UTC),
    )[0]
    app = create_app()
    _install_runtime(
        app,
        _StubTopic4Runtime(candidate, report, claim),
        scopes=frozenset({"topic4:review:read"}),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"authorization": "Bearer topic4-token", "x-trace-id": TRACE_ID}
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            f"/internal/topic4/verifications/{report.verification_id}/reviews/decisions",
            headers={
                **headers,
                "Idempotency-Key": "topic4-api-review-00000000000000000002",
            },
            json={
                "review_task_id": str(uuid4()),
                "decision": "REVISE",
                "rationale": "not authorized",
                "expected_task_version": 1,
                "expected_state_version": 1,
            },
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_topic4_api_fails_closed_when_runtime_is_unavailable() -> None:
    app = create_app()
    candidate = _candidate()
    report = _report(candidate)
    claim = DeterministicClaimExtractor().extract(
        candidate,
        verification_id=report.verification_id,
        trace_id=TRACE_ID,
        tenant_id=TENANT_ID,
        created_at=datetime.now(UTC),
    )[0]
    _install_runtime(app, _StubTopic4Runtime(candidate, report, claim))
    del app.state.topic4_runtime
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/internal/topic4/health",
            headers={"authorization": "Bearer topic4-token", "x-trace-id": TRACE_ID},
        )
    assert response.status_code == 503
    assert response.json()["error"]["error_code"] == "LIYAN-DATABASE-UNAVAILABLE"


@pytest.mark.asyncio
async def test_topic4_revision_route_and_error_mapping_are_stable() -> None:
    candidate = _candidate()
    report = _report(candidate)
    claim = DeterministicClaimExtractor().extract(
        candidate,
        verification_id=report.verification_id,
        trace_id=TRACE_ID,
        tenant_id=TENANT_ID,
        created_at=datetime.now(UTC),
    )[0]
    runtime = _StubTopic4Runtime(candidate, report, claim)
    app = create_app()
    _install_runtime(app, runtime)
    request = SimpleNamespace(
        app=app,
        state=SimpleNamespace(trace_id=TRACE_ID),
    )
    command = RevisionCommand.model_construct(
        request=SimpleNamespace(verification_id=report.verification_id),
        patches=[SimpleNamespace()],
        prompt_bundle_version="topic4-prompts-v1",
    )
    context = TenantContext(
        tenant_id=TENANT_ID,
        subject_ref="subject:topic4-api",
        roles=frozenset({"teacher"}),
        scopes=frozenset({"topic4:revision:write"}),
        trace_id=TRACE_ID,
    )
    with tenant_scope(context):
        response = await create_revision(request, command)

    assert response["payload"]["cycle"]["verification_id"] == str(report.verification_id)
    existing = LiyanError(
        ErrorCode.CONTRACT_INVALID,
        "invalid",
        category=ErrorCategory.CONTRACT,
        status_code=422,
    )
    assert map_topic4_error(existing) is existing
    assert map_topic4_error(ReleaseError("denied")).code == ErrorCode.TOPIC4_RELEASE_DENIED
    assert map_topic4_error(RuntimeError("failed")).code == ErrorCode.TOPIC4_INTEGRITY_FAILED
