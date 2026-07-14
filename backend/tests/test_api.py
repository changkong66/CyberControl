from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from liyans.core.settings import get_settings
from liyans.infrastructure.database import DatabaseHealthResult
from liyans.main import create_app


class StubDatabaseHealthProbe:
    def __init__(self, *, healthy: bool = True) -> None:
        self._healthy = healthy

    async def check(self) -> DatabaseHealthResult:
        return DatabaseHealthResult(healthy=self._healthy, latency_ms=0.25)


@pytest.mark.asyncio
async def test_health_and_envelope_validation(monkeypatch, tmp_path: Path, make_envelope) -> None:
    monkeypatch.setenv("LIYAN_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LIYAN_PROVIDER_POLICY_POLL_SECONDS", "60")
    get_settings.cache_clear()
    app = create_app()
    headers = {
        "x-tenant-id": "tenant-a",
        "x-subject-ref": "subject:test",
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
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["database"]["status"] == "down"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_internal_api_requires_tenant_headers(monkeypatch, tmp_path: Path) -> None:
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
        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "LIYAN-TENANT-CONTEXT-MISSING"
    get_settings.cache_clear()
