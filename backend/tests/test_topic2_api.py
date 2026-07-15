from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from liyans_contracts.common import canonical_sha256

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext
from liyans.infrastructure.security import AuthenticatedPrincipal
from liyans.main import create_app


class StubTokenVerifier:
    def __init__(self, scopes: frozenset[str]) -> None:
        self.scopes = scopes

    async def verify(self, token: str) -> AuthenticatedPrincipal:
        if token != "test-token":
            raise LiyanError(
                ErrorCode.AUTH_TOKEN_INVALID,
                "The bearer token is invalid.",
                category=ErrorCategory.AUTH,
                status_code=401,
            )
        now = datetime.now(UTC)
        return AuthenticatedPrincipal(
            issuer="https://issuer.test",
            subject="subject:student",
            tenant_id="tenant-a",
            roles=frozenset({"student"}),
            scopes=self.scopes,
            token_id="topic2-test-jti",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )


class StubTenantAuthorizer:
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


class StubTopic2Orchestrator:
    def __init__(self) -> None:
        self.event = None
        self.initialization_request = None
        self.profile_request = None
        self.restore_request = None
        self.batch_request = None

    async def record_behavior(self, event, *, idempotency_key: str):
        self.event = event
        return {"event": {"event_id": str(event.event_id), "key": idempotency_key}}

    async def rebuild_profile(self, **kwargs):
        self.profile_request = kwargs
        return {"profile": {"profile_version": 1}}

    async def initialize_learner(self, **kwargs):
        self.initialization_request = kwargs
        return {"profile": {"profile_version": 1}, "memory_states": []}

    async def restore_profile(self, **kwargs):
        self.restore_request = kwargs
        return {"profile": {"profile_version": 2}}

    async def refresh_memory(self, **_kwargs):
        return {"memory_states": []}

    async def refresh_due_memory(self, **kwargs):
        self.batch_request = kwargs
        return {"schema_version": "topic2.memory-batch-refresh.v1", "group_count": 0}

    async def generate_path(self, **_kwargs):
        return {"learning_path": {"snapshot": {"path_version": 1}}}

    async def agent_context(self, learner_ref: str, course_id: str):
        return {
            "schema_version": "topic2.agent-context.v1",
            "learner_ref": learner_ref,
            "course_id": course_id,
        }


class StubTopic2Service:
    async def latest_profile(self, _learner_ref: str, _course_id: str):
        return None

    async def list_profile_versions(self, *_args, **_kwargs):
        return []

    async def latest_memory_states(self, *_args, **_kwargs):
        return []

    async def latest_learning_path(self, *_args, **_kwargs):
        return None

    async def list_learning_paths(self, *_args, **_kwargs):
        return []


def install_stubs(app, scopes: frozenset[str]):
    orchestrator = StubTopic2Orchestrator()
    app.state.token_verifier = StubTokenVerifier(scopes)
    app.state.tenant_authorizer = StubTenantAuthorizer()
    app.state.topic2_orchestrator = orchestrator
    app.state.topic2_service = StubTopic2Service()
    return orchestrator


def headers(
    *,
    idempotency_key: str = "topic2-api-idempotency-0001",
    **extra: str,
) -> dict[str, str]:
    return {
        "authorization": "Bearer test-token",
        "x-trace-id": "a" * 32,
        "Idempotency-Key": idempotency_key,
        **extra,
    }


def behavior_body() -> dict:
    payload = {"question_id": "QUESTION_ATC_001", "answer": "3/(s+2)"}
    return {
        "event_id": str(uuid4()),
        "source_event_id": "tester-event-0000000001",
        "learner_ref": "subject:student",
        "course_id": "CRS_ATC_001",
        "kp_id": "KP_ATC_301_TRANSFER_FUNCTION",
        "event_type": "ANSWER_SUBMITTED",
        "source_type": "TESTER",
        "correctness": 1,
        "score": 0.9,
        "attempt_count": 1,
        "payload": payload,
        "payload_sha256": canonical_sha256(payload),
        "occurred_at": datetime.now(UTC).isoformat(),
    }


@pytest.mark.asyncio
async def test_topic2_behavior_uses_global_envelope_and_server_identity() -> None:
    app = create_app()
    orchestrator = install_stubs(app, frozenset({"topic2:behavior:write"}))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/internal/topic2/behavior-events",
            headers=headers(),
            json=behavior_body(),
        )
    assert response.status_code == 200
    document = response.json()
    assert document["schema_version"] == "topic3.envelope.v1"
    assert document["tenant_id"] == "tenant-a"
    assert document["subject_ref"] == "subject:student"
    assert document["message_kind"] == "RESULT"
    assert orchestrator.event.learner_ref == "subject:student"


@pytest.mark.asyncio
async def test_topic2_rejects_client_tenant_and_missing_scope() -> None:
    app = create_app()
    install_stubs(app, frozenset({"topic2:profile:read"}))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    invalid = behavior_body()
    invalid["tenant_id"] = "forged-tenant"
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        forbidden = await client.post(
            "/internal/topic2/behavior-events",
            headers=headers(),
            json=behavior_body(),
        )
    assert forbidden.status_code == 403

    install_stubs(app, frozenset({"topic2:behavior:write"}))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        rejected_identity = await client.post(
            "/internal/topic2/behavior-events",
            headers=headers(),
            json=invalid,
        )
    assert rejected_identity.status_code == 422


@pytest.mark.asyncio
async def test_topic2_generation_requires_operation_identity_and_exposes_not_found() -> None:
    app = create_app()
    orchestrator = install_stubs(
        app,
        frozenset({"topic2:profile:write", "topic2:profile:read"}),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    body = {"operation_id": str(uuid4()), "requested_at": datetime.now(UTC).isoformat()}
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        generated = await client.post(
            "/internal/topic2/learners/subject:student/courses/CRS_ATC_001/profiles/rebuild",
            headers=headers(),
            json=body,
        )
        missing = await client.get(
            "/internal/topic2/learners/subject:student/courses/CRS_ATC_001/profiles/latest",
            headers=headers(),
        )
    assert generated.status_code == 200
    assert orchestrator.profile_request["operation_id"] == UUID(body["operation_id"])
    assert missing.status_code == 404
    assert missing.json()["error"]["error_code"] == "LIYAN-TOPIC2-NOT-FOUND"


@pytest.mark.asyncio
async def test_topic2_route_fails_closed_without_runtime_service() -> None:
    app = create_app()
    app.state.token_verifier = StubTokenVerifier(frozenset({"topic2:behavior:write"}))
    app.state.tenant_authorizer = StubTenantAuthorizer()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/internal/topic2/behavior-events",
            headers=headers(),
            json=behavior_body(),
        )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_topic2_rejects_oversized_path_and_behavior_payloads() -> None:
    app = create_app()
    install_stubs(
        app,
        frozenset({"topic2:behavior:write", "topic2:path:write"}),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    oversized_behavior = behavior_body()
    oversized_behavior["payload"] = {"blob": "x" * (64 * 1024)}
    oversized_behavior["payload_sha256"] = canonical_sha256(oversized_behavior["payload"])
    path_body = {
        "operation_id": str(uuid4()),
        "requested_at": datetime.now(UTC).isoformat(),
        "target_goal": "Stress test",
        "target_kp_ids": [f"KP_ATC_{index:04d}" for index in range(501)],
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        behavior_response = await client.post(
            "/internal/topic2/behavior-events",
            headers=headers(),
            json=oversized_behavior,
        )
        path_response = await client.post(
            "/internal/topic2/learners/subject:student/courses/CRS_ATC_001/paths/generate",
            headers=headers(),
            json=path_body,
        )
    assert behavior_response.status_code == 422
    assert path_response.status_code == 422


@pytest.mark.asyncio
async def test_topic2_lifecycle_and_batch_routes_preserve_operation_identity() -> None:
    app = create_app()
    orchestrator = install_stubs(
        app,
        frozenset(
            {
                "topic2:profile:write",
                "topic2:memory:write",
                "topic2:memory:batch",
            }
        ),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    operation_id = uuid4()
    body = {
        "operation_id": str(operation_id),
        "requested_at": datetime.now(UTC).isoformat(),
    }
    profile_id = uuid4()
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        initialized = await client.post(
            "/internal/topic2/learners/subject:student/courses/CRS_ATC_001/initialize",
            headers=headers(idempotency_key="topic2-topic2-topic2-topic2"),
            json=body,
        )
        restored = await client.post(
            f"/internal/topic2/profiles/{profile_id}/restore",
            headers=headers(idempotency_key="restore-restore-restore-restore"),
            json=body,
        )
        batch = await client.post(
            "/internal/topic2/memory/jobs/refresh-due?limit=25",
            headers=headers(idempotency_key="memory-memory-memory-memory"),
            json=body,
        )
    assert initialized.status_code == 200
    assert restored.status_code == 200
    assert batch.status_code == 200
    assert orchestrator.initialization_request["operation_id"] == operation_id
    assert orchestrator.restore_request["profile_id"] == profile_id
    assert orchestrator.batch_request["limit"] == 25
