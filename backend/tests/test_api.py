from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from liyans.core.settings import get_settings
from liyans.main import create_app


def test_health_and_envelope_validation(monkeypatch, tmp_path: Path, make_envelope) -> None:
    monkeypatch.setenv("LIYAN_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LIYAN_PROVIDER_POLICY_POLL_SECONDS", "60")
    get_settings.cache_clear()
    app = create_app()
    headers = {
        "x-tenant-id": "tenant-a",
        "x-subject-ref": "subject:test",
        "x-trace-id": "a" * 32,
    }
    with TestClient(app, raise_server_exceptions=False) as client:
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["task_queue_running"] is True

        envelope = make_envelope(0)
        valid = client.post(
            "/internal/topic3/envelopes/validate",
            headers=headers,
            json=envelope.model_dump(mode="json"),
        )
        assert valid.status_code == 200
        assert valid.json()["envelope"]["schema_version"] == "topic3.envelope.v1"

        invalid = client.post(
            "/internal/topic3/envelopes/validate",
            headers=headers,
            json={"schema_version": "topic3.envelope.v1"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["error_code"] == "LIYAN-CONTRACT-INVALID"
    get_settings.cache_clear()


def test_internal_api_requires_tenant_headers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LIYAN_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/internal/topic3/envelopes/validate", json={})
        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "LIYAN-TENANT-CONTEXT-MISSING"
    get_settings.cache_clear()
