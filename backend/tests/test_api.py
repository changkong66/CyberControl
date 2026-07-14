from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.settings import get_settings
from liyans.core.tenant import TenantContext
from liyans.infrastructure.database import DatabaseHealthResult
from liyans.infrastructure.security import AuthenticatedPrincipal
from liyans.main import create_app


class StubDatabaseHealthProbe:
    def __init__(self, *, healthy: bool = True) -> None:
        self._healthy = healthy

    async def check(self) -> DatabaseHealthResult:
        return DatabaseHealthResult(healthy=self._healthy, latency_ms=0.25)


class StubTokenVerifier:
    def __init__(self, *, scopes: frozenset[str] | None = None) -> None:
        self._scopes = scopes or frozenset()

    async def verify(self, token: str) -> AuthenticatedPrincipal:
        if token != "test-token":
            raise LiyanError(
                ErrorCode.AUTH_TOKEN_INVALID,
                "The bearer token is invalid or expired.",
                category=ErrorCategory.AUTH,
                status_code=401,
            )
        now = datetime.now(UTC)
        return AuthenticatedPrincipal(
            issuer="https://issuer.test",
            subject="subject:test",
            tenant_id="tenant-a",
            roles=frozenset({"student"}),
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


def install_auth_stubs(app, *, scopes: frozenset[str]) -> None:
    app.state.token_verifier = StubTokenVerifier(scopes=scopes)
    app.state.tenant_authorizer = StubTenantAuthorizer()
    app.state.auth_configured = True


@pytest.mark.asyncio
async def test_health_and_envelope_validation(monkeypatch, tmp_path: Path, make_envelope) -> None:
    monkeypatch.setenv("LIYAN_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LIYAN_PROVIDER_POLICY_POLL_SECONDS", "60")
    get_settings.cache_clear()
    app = create_app()
    headers = {
        "authorization": "Bearer test-token",
        "x-trace-id": "a" * 32,
    }
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client,
    ):
        app.state.database_health = StubDatabaseHealthProbe()
        install_auth_stubs(app, scopes=frozenset({"topic3:validate"}))
        ready = await client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["task_queue_running"] is True
        assert ready.json()["database"]["status"] == "up"

        envelope = make_envelope(0)
        valid = await client.post(
            "/internal/topic3/envelopes/validate",
            headers=headers,
            json=envelope.model_dump(mode="json"),
        )
        assert valid.status_code == 200
        assert valid.json()["envelope"]["schema_version"] == "topic3.envelope.v1"

        invalid = await client.post(
            "/internal/topic3/envelopes/validate",
            headers=headers,
            json={"schema_version": "topic3.envelope.v1"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["error_code"] == "LIYAN-CONTRACT-INVALID"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_readiness_fails_closed_when_database_is_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LIYAN_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        app.state.database_health = StubDatabaseHealthProbe(healthy=False)
        install_auth_stubs(app, scopes=frozenset())
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["database"]["status"] == "down"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_internal_api_requires_bearer_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LIYAN_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client,
    ):
        response = await client.post("/internal/topic3/envelopes/validate", json={})
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json()["error"]["error_code"] == "LIYAN-AUTH-REQUIRED"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_internal_api_rejects_client_identity_headers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LIYAN_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        response = await client.post(
            "/internal/topic3/envelopes/validate",
            headers={
                "authorization": "Bearer test-token",
                "x-tenant-id": "forged-tenant",
            },
            json={},
        )
    assert response.status_code == 400
    assert response.json()["error"]["error_code"] == "LIYAN-AUTH-IDENTITY-HEADER-FORBIDDEN"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_internal_api_enforces_route_scopes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LIYAN_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        install_auth_stubs(app, scopes=frozenset())
        response = await client.post(
            "/internal/topic3/envelopes/validate",
            headers={"authorization": "Bearer test-token"},
            json={},
        )
    assert response.status_code == 403
    assert response.json()["error"]["error_code"] == "LIYAN-AUTH-FORBIDDEN"
    get_settings.cache_clear()
