from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext
from liyans.infrastructure.security import AuthenticatedPrincipal
from liyans.main import create_app


class StubTokenVerifier:
    def __init__(self, scopes: frozenset[str]) -> None:
        self._scopes = scopes

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
            subject="subject:test",
            tenant_id="tenant-a",
            roles=frozenset({"instructor"}),
            scopes=self._scopes,
            token_id="test-jti",
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


class StubTopic1Service:
    def __init__(self) -> None:
        self.last_course_request = None
        self.import_called = False

    async def list_courses(self):
        return []

    async def get_course(self, _course_id):
        return Dumpable({"course_id": "CRS_ATC_001"})

    async def get_graph(self, _course_id):
        return Dumpable({"course": {"course_id": "CRS_ATC_001"}})

    async def list_snapshots(self, _course_id):
        return [Dumpable({"snapshot_id": str(uuid4()), "graph_version": 1})]

    async def upsert_course(self, **kwargs):
        self.last_course_request = kwargs
        return {"snapshot": {"graph_version": 1}}

    async def import_bundle(self, _body, *, idempotency_key: str):
        del idempotency_key
        self.import_called = True
        return {"snapshot": {"graph_version": 1}}

    async def upsert_knowledge_point(self, **_kwargs):
        return {"snapshot": {"graph_version": 2}}

    async def delete_knowledge_point(self, **_kwargs):
        return {"snapshot": {"graph_version": 3}}

    async def upsert_prerequisite(self, **_kwargs):
        return {"snapshot": {"graph_version": 4}}

    async def delete_prerequisite(self, **_kwargs):
        return {"snapshot": {"graph_version": 5}}

    async def freeze_graph(self, _course_id, *, idempotency_key: str):
        del idempotency_key
        return {"snapshot": {"graph_version": 6}}

    async def rollback_snapshot(self, _snapshot_id, *, idempotency_key: str):
        del idempotency_key
        return {"snapshot": {"graph_version": 7}}


class Dumpable:
    def __init__(self, document: dict) -> None:
        self._document = document

    def model_dump(self, *, mode: str):
        assert mode == "json"
        return self._document


def install_stubs(app, service: StubTopic1Service, scopes: frozenset[str]) -> None:
    app.state.token_verifier = StubTokenVerifier(scopes)
    app.state.tenant_authorizer = StubTenantAuthorizer()
    app.state.topic1_service = service


def auth_headers(**extra: str) -> dict[str, str]:
    return {
        "authorization": "Bearer test-token",
        "x-trace-id": "a" * 32,
        **extra,
    }


def course_body() -> dict:
    return {
        "course_code": "ATC",
        "title": "Automatic Control Theory",
        "description": "Classical control foundations.",
        "credit_hours": 64,
        "status": "ACTIVE",
        "authority_sources": [],
    }


def import_body() -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "schema_version": "topic1.import-bundle.v1",
        "import_id": str(uuid4()),
        "expected_parent_version": None,
        "requested_at": now,
        "content": {
            "course": {
                "schema_version": "topic1.course.v1",
                "course_id": "CRS_ATC_001",
                "revision": 1,
                "course_code": "ATC",
                "title": "Automatic Control Theory",
                "description": "Classical control foundations.",
                "locale": "zh-CN",
                "academic_level": "UNDERGRADUATE",
                "credit_hours": 64,
                "status": "ACTIVE",
                "authority_sources": [],
                "created_at": now,
                "updated_at": now,
            },
            "knowledge_points": [],
            "prerequisites": [],
            "misconceptions": [],
            "textbooks": [],
            "textbook_sections": [],
            "textbook_mappings": [],
            "golden_questions": [],
        },
    }


@pytest.mark.asyncio
async def test_topic1_read_response_uses_versioned_envelope() -> None:
    app = create_app()
    service = StubTopic1Service()
    install_stubs(app, service, frozenset({"topic1:read"}))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/internal/topic1/courses", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["schema_version"] == "topic1.api-envelope.v1"
    assert response.json()["data"] == {"courses": []}


@pytest.mark.asyncio
async def test_topic1_write_requires_scope_and_idempotency_key() -> None:
    app = create_app()
    service = StubTopic1Service()
    install_stubs(app, service, frozenset({"topic1:read"}))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        forbidden = await client.put(
            "/internal/topic1/courses/CRS_ATC_001",
            headers=auth_headers(**{"Idempotency-Key": "course-create-0001"}),
            json=course_body(),
        )
    assert forbidden.status_code == 403

    install_stubs(app, service, frozenset({"topic1:write"}))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing_key = await client.put(
            "/internal/topic1/courses/CRS_ATC_001",
            headers=auth_headers(),
            json=course_body(),
        )
    assert missing_key.status_code == 422
    assert missing_key.json()["error"]["error_code"] == "LIYAN-CONTRACT-INVALID"


@pytest.mark.asyncio
async def test_topic1_write_never_accepts_client_tenant_identity() -> None:
    app = create_app()
    service = StubTopic1Service()
    install_stubs(app, service, frozenset({"topic1:write"}))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/internal/topic1/courses/CRS_ATC_001",
            headers=auth_headers(**{"Idempotency-Key": "course-create-0001"}),
            json=course_body(),
        )
    assert response.status_code == 200
    assert "tenant_id" not in service.last_course_request["document"]
    assert service.last_course_request["course_id"] == "CRS_ATC_001"


@pytest.mark.asyncio
async def test_topic1_import_rejects_declared_oversize_before_service() -> None:
    app = create_app()
    service = StubTopic1Service()
    install_stubs(app, service, frozenset({"topic1:import"}))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/internal/topic1/imports",
            headers=auth_headers(
                **{
                    "Idempotency-Key": "topic1-import-0001",
                    "Content-Length": str(6 * 1024 * 1024),
                }
            ),
            json=import_body(),
        )
    assert response.status_code == 413
    assert response.json()["error"]["error_code"] == "LIYAN-TOPIC1-IMPORT-LIMIT"
    assert service.import_called is False


@pytest.mark.asyncio
async def test_topic1_import_rejects_chunked_oversize_before_model_parsing() -> None:
    app = create_app()
    service = StubTopic1Service()
    install_stubs(app, service, frozenset({"topic1:import"}))

    async def oversized_chunks():
        for _ in range(66):
            yield b"x" * (80 * 1024)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/internal/topic1/imports",
            headers={"Idempotency-Key": "topic1-import-chunked-0001"},
            content=oversized_chunks(),
        )
    assert response.status_code == 413
    assert response.json()["error"]["error_code"] == "LIYAN-TOPIC1-IMPORT-LIMIT"
    assert len(response.headers["x-trace-id"]) == 32
    assert service.import_called is False


@pytest.mark.asyncio
async def test_topic1_import_replays_valid_chunked_body() -> None:
    app = create_app()
    service = StubTopic1Service()
    install_stubs(app, service, frozenset({"topic1:import"}))
    payload = json.dumps(import_body()).encode("utf-8")

    async def payload_chunks():
        midpoint = len(payload) // 2
        yield payload[:midpoint]
        yield payload[midpoint:]

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/internal/topic1/imports",
            headers=auth_headers(
                **{
                    "Idempotency-Key": "topic1-import-chunked-0002",
                    "Content-Type": "application/json",
                }
            ),
            content=payload_chunks(),
        )
    assert response.status_code == 200
    assert service.import_called is True


@pytest.mark.asyncio
async def test_topic1_all_route_adapters_delegate_to_service() -> None:
    app = create_app()
    service = StubTopic1Service()
    install_stubs(
        app,
        service,
        frozenset(
            {
                "topic1:read",
                "topic1:write",
                "topic1:import",
                "topic1:freeze",
                "topic1:rollback",
            }
        ),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    headers = auth_headers(**{"Idempotency-Key": "topic1-route-test-0001"})
    kp_body = {
        "title": "Transfer Function",
        "summary": "Laplace-domain model.",
        "learning_objectives": ["Derive the model."],
        "category": "MODELING",
        "difficulty_score": 0.4,
        "estimated_minutes": 90,
    }
    edge_body = {
        "prerequisite_kp_id": "KP_ATC_301_传递函数",
        "dependent_kp_id": "KP_ATC_302_时域响应",
        "strength": 1,
        "rationale": "Modeling precedes response analysis.",
    }
    snapshot_id = uuid4()
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        responses = [
            await client.get("/internal/topic1/courses/CRS_ATC_001", headers=auth_headers()),
            await client.get(
                "/internal/topic1/courses/CRS_ATC_001/graph",
                headers=auth_headers(),
            ),
            await client.put(
                "/internal/topic1/courses/CRS_ATC_001/knowledge-points/KP_ATC_301_传递函数",
                headers=headers,
                json=kp_body,
            ),
            await client.delete(
                "/internal/topic1/courses/CRS_ATC_001/knowledge-points/KP_ATC_301_传递函数"
                "?expected_revision=1",
                headers=headers,
            ),
            await client.put(
                "/internal/topic1/courses/CRS_ATC_001/prerequisites/EDGE_ATC_001",
                headers=headers,
                json=edge_body,
            ),
            await client.delete(
                "/internal/topic1/courses/CRS_ATC_001/prerequisites/EDGE_ATC_001"
                "?expected_revision=1",
                headers=headers,
            ),
            await client.post(
                "/internal/topic1/imports",
                headers=headers,
                json=import_body(),
            ),
            await client.post(
                "/internal/topic1/courses/CRS_ATC_001/snapshots",
                headers=headers,
            ),
            await client.get(
                "/internal/topic1/courses/CRS_ATC_001/snapshots",
                headers=auth_headers(),
            ),
            await client.post(
                f"/internal/topic1/snapshots/{snapshot_id}/rollback",
                headers=headers,
            ),
        ]
    assert all(response.status_code == 200 for response in responses)


@pytest.mark.asyncio
async def test_topic1_route_fails_closed_without_service() -> None:
    app = create_app()
    app.state.token_verifier = StubTokenVerifier(frozenset({"topic1:read"}))
    app.state.tenant_authorizer = StubTenantAuthorizer()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/internal/topic1/courses", headers=auth_headers())
    assert response.status_code == 503
