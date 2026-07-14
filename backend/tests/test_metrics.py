from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from liyans.infrastructure.observability.metrics import HTTPMetricsMiddleware, PlatformMetrics


def test_metrics_use_isolated_registries_and_never_label_raw_tenants() -> None:
    first = PlatformMetrics()
    second = PlatformMetrics()
    first.observe_http(
        method="GET",
        route="/internal/topic3/sse/stream",
        status_code=200,
        duration_seconds=0.01,
    )
    first.observe_outbox("delivery", "published")
    first.observe_sse("fanout", "delivered", 2)
    first.observe_database_health(healthy=True, latency_ms=1.5)
    first.set_component_ready("sse_notification_bridge", True)

    rendered = first.render().decode("utf-8")
    assert "liyans_http_requests_total" in rendered
    assert "liyans_outbox_operations_total" in rendered
    assert "liyans_sse_operations_total" in rendered
    assert "tenant-secret-value" not in rendered
    assert second.render() != b""


@pytest.mark.asyncio
async def test_http_metrics_normalize_unmatched_routes_and_status_classes() -> None:
    metrics = PlatformMetrics()
    app = FastAPI()
    app.add_middleware(HTTPMetricsMiddleware, metrics=metrics)

    @app.get("/bounded/{item_id}")
    async def bounded(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/bounded/untrusted-cardinality-value")).status_code == 200
        assert (await client.get("/not-found/untrusted-cardinality-value")).status_code == 404

    rendered = metrics.render().decode("utf-8")
    assert 'route="/bounded/{item_id}"' in rendered
    assert 'route="unmatched"' in rendered
    assert "untrusted-cardinality-value" not in rendered
