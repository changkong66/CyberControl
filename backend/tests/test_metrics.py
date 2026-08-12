from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from liyans.api.routes.metrics import metrics as metrics_route
from liyans.infrastructure.observability.metrics import (
    HTTPMetricsMiddleware,
    PlatformMetrics,
)


def test_batched_histogram_matches_prometheus_histogram_observation_semantics() -> None:
    metrics = PlatformMetrics()
    observations = (0.004, 0.011, 0.7, 11.0)
    for value in observations:
        metrics.observe_sse_latency("fanout_locked", value)

    rendered = metrics.render().decode("utf-8")
    assert 'liyans_sse_latency_seconds_bucket{le="0.005",stage="fanout_locked"} 1.0' in rendered
    assert 'liyans_sse_latency_seconds_bucket{le="0.01",stage="fanout_locked"} 1.0' in rendered
    assert 'liyans_sse_latency_seconds_bucket{le="1.0",stage="fanout_locked"} 3.0' in rendered
    assert 'liyans_sse_latency_seconds_bucket{le="+Inf",stage="fanout_locked"} 4.0' in rendered
    assert 'liyans_sse_latency_seconds_count{stage="fanout_locked"} 4.0' in rendered
    assert 'liyans_sse_latency_seconds_sum{stage="fanout_locked"} 11.715' in rendered


def test_batched_histogram_observations_are_not_lost_under_concurrency() -> None:
    from concurrent.futures import ThreadPoolExecutor

    metrics = PlatformMetrics()

    def observe_many() -> None:
        for _ in range(250):
            metrics.observe_sse_latency("fanout_locked", 0.01)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _index: observe_many(), range(8)))

    rendered = metrics.render().decode("utf-8")
    assert 'liyans_sse_latency_seconds_count{stage="fanout_locked"} 2000.0' in rendered


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
    first.set_database_pool_capacity("api", 30)
    first.observe_database_pool_checkout("api", 1)
    first.observe_database_pool_checkout("api", -1)
    first.observe_database_pool_acquisition_timeout("unexpected-untrusted-pool")

    rendered = first.render().decode("utf-8")
    assert "liyans_http_requests_total" in rendered
    assert "liyans_outbox_operations_total" in rendered
    assert "liyans_sse_operations_total" in rendered
    assert 'liyans_database_pool_capacity{pool="api"} 30.0' in rendered
    assert 'liyans_database_pool_checked_out{pool="api"} 0.0' in rendered
    assert 'liyans_database_pool_acquisition_timeouts_total{pool="other"} 1.0' in rendered
    assert "tenant-secret-value" not in rendered
    assert second.render() != b""


def test_database_pool_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="capacity"):
        PlatformMetrics().set_database_pool_capacity("api", 0)


def test_metrics_normalize_unknown_method_and_ignore_zero_pool_delta() -> None:
    metrics = PlatformMetrics()

    metrics.observe_http(
        method="UNTRUSTED",
        route="/bounded",
        status_code=200,
        duration_seconds=0,
    )
    metrics.observe_database_pool_checkout("api", 0)

    rendered = metrics.render().decode("utf-8")
    assert 'method="OTHER"' in rendered
    assert 'liyans_database_pool_checked_out{pool="api"}' not in rendered


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


@pytest.mark.asyncio
async def test_metrics_route_renders_platform_registry() -> None:
    platform_metrics = PlatformMetrics()
    platform_metrics.observe_sse("fanout", "delivered")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(metrics=platform_metrics)))

    response = await metrics_route(request)

    assert response.media_type == platform_metrics.content_type
    assert b"liyans_sse_operations_total" in response.body


@pytest.mark.asyncio
async def test_http_metrics_middleware_passes_non_http_scopes_through() -> None:
    received_scopes: list[dict] = []

    async def app(scope, _receive, _send) -> None:
        received_scopes.append(scope)

    async def receive() -> dict:
        return {"type": "websocket.disconnect"}

    async def send(_message: dict) -> None:
        return None

    middleware = HTTPMetricsMiddleware(app, metrics=PlatformMetrics())
    scope = {"type": "websocket"}

    await middleware(scope, receive, send)

    assert received_scopes == [scope]
