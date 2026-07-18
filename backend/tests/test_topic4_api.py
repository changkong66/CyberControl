from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from integration.test_postgres_topic4 import _verification_request
from liyans_contracts.topic4_c1 import ClaimV1
from test_topic4_c12_release import _authorization, _report
from test_topic4_control_plane import TENANT_ID, TRACE_ID, _candidate

from liyans.api.routes.topic4 import RevisionCommand, create_revision
from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.domains.release.engine import ReleaseError
from liyans.domains.verification.claim_extraction import DeterministicClaimExtractor
from liyans.domains.verification.runtime import map_topic4_error
from liyans.infrastructure.security import AuthenticatedPrincipal
from liyans.infrastructure.streaming.sse import (
    InMemorySSEReplayLog,
    ReplayCursorCodec,
    SSEBroker,
)
from liyans.main import create_app


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
        return authorization

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


def _install_runtime(app, runtime: _StubTopic4Runtime) -> None:
    scopes = frozenset(
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
    authorization = _authorization(
        candidate,
        report,
        issued_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
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
        published_batch = await client.post(
            "/internal/topic4/release/publications/batch",
            headers=headers,
            json={"publications": [publication_body, publication_body]},
        )
        history = await client.get(
            f"/internal/topic4/release/history?verification_id={report.verification_id}&limit=20",
            headers=headers,
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
        evidence,
        revisions,
        valid,
        issued,
        published,
        published_batch,
        history,
        replay,
    )
    assert all(response.status_code < 300 for response in responses), [
        (response.status_code, response.text) for response in responses
    ]
    assert batch.json()["payload"]["verifications"][0]["verification"]["verification_id"] == str(
        request_payload.verification_id
    )
    assert runtime.enqueued == [request_payload.verification_id]
    assert replay.json()["payload"]["events"][0]["event_type"] == ("topic4.publication.committed")


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
