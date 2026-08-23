from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

import liyans.infrastructure.observability.metrics as metrics_module
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


def test_metrics_expose_bounded_jemalloc_allocator_statistics() -> None:
    metrics = PlatformMetrics()
    metrics._jemalloc_stats = SimpleNamespace(
        snapshot=lambda: {
            "allocated": 10,
            "active": 20,
            "resident": 30,
            "retained": 40,
            "arenas": 1,
        }
    )

    rendered = metrics.render().decode("utf-8")

    assert "liyans_jemalloc_available 1.0" in rendered
    assert 'liyans_jemalloc_bytes{metric="allocated"} 10.0' in rendered
    assert 'liyans_jemalloc_bytes{metric="retained"} 40.0' in rendered
    assert "liyans_jemalloc_arenas 1.0" in rendered
    assert "tenant" not in rendered
    assert "cursor" not in rendered


@pytest.mark.asyncio
async def test_memory_diagnostics_are_opt_in_and_expose_only_bounded_fields(monkeypatch) -> None:
    monkeypatch.setenv("LIYAN_MEMORY_DIAGNOSTICS", "true")
    monkeypatch.setenv("LIYAN_MEMORY_DIAGNOSTICS_INTERVAL_SECONDS", "5")
    metrics = PlatformMetrics()

    log_info = Mock()
    monkeypatch.setattr(metrics_module.logger, "info", log_info)
    await metrics.run_memory_diagnostics_once()
    rendered = metrics.render().decode("utf-8")

    assert "liyans_memory_diagnostics_gauge" in rendered
    assert "tracemalloc_current_bytes" in rendered
    diagnostics = [
        " ".join(str(argument) for argument in call.args)
        for call in log_info.call_args_list
        if call.args and "Memory diagnostics snapshot" in str(call.args[0])
    ]
    assert diagnostics
    assert "tenant_id" not in diagnostics[-1]
    assert "Authorization" not in diagnostics[-1]
    assert "cursor" not in diagnostics[-1]


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


@pytest.mark.asyncio
async def test_metrics_scrape_does_not_execute_heavy_memory_diagnostics(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LIYAN_MEMORY_DIAGNOSTICS", "true")
    metrics = PlatformMetrics()
    invoked = False

    def blocked_collector() -> None:
        nonlocal invoked
        invoked = True
        time.sleep(0.05)

    monkeypatch.setattr(metrics, "_refresh_memory_diagnostics", blocked_collector, raising=False)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(metrics=metrics)))

    await metrics_route(request)

    assert invoked is False


@pytest.mark.asyncio
async def test_memory_diagnostics_sampler_keeps_scrape_and_heartbeat_independent(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LIYAN_MEMORY_DIAGNOSTICS", "true")
    metrics = PlatformMetrics()
    started = threading.Event()
    release = threading.Event()

    def controlled_collector(_loop):
        started.set()
        assert release.wait(1.0)
        return {
            "values": {"tracemalloc_current_bytes": 1},
            "task_names": (),
            "object_types": (),
            "top_allocations": (),
            "stage_durations": (),
        }

    monkeypatch.setattr(metrics, "_collect_memory_diagnostics", controlled_collector, raising=False)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(metrics=metrics)))

    await metrics.start_memory_diagnostics()
    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.001)
        assert started.is_set()

        heartbeat = asyncio.create_task(asyncio.sleep(0))
        response = await metrics_route(request)
        await asyncio.wait_for(heartbeat, timeout=0.2)

        assert response.body
        assert heartbeat.done()
    finally:
        release.set()
        await metrics.close()


@pytest.mark.asyncio
async def test_memory_diagnostics_sampler_has_one_owner_and_no_overlap(monkeypatch) -> None:
    monkeypatch.setenv("LIYAN_MEMORY_DIAGNOSTICS", "true")
    metrics = PlatformMetrics()
    active = 0
    maximum_active = 0
    calls = 0
    lock = threading.Lock()

    def controlled_collector(_loop):
        nonlocal active, maximum_active, calls
        with lock:
            active += 1
            calls += 1
            maximum_active = max(maximum_active, active)
        try:
            time.sleep(0.01)
            return {
                "values": {"tracemalloc_current_bytes": calls},
                "task_names": (),
                "object_types": (),
                "top_allocations": (),
                "stage_durations": (),
            }
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(metrics, "_collect_memory_diagnostics", controlled_collector, raising=False)
    metrics._memory_diagnostics_interval = 0.001

    await metrics.start_memory_diagnostics()
    same_task = metrics.memory_diagnostics_task
    await metrics.start_memory_diagnostics()
    await asyncio.sleep(0.08)
    await metrics.close()
    await metrics.close()

    assert same_task is not None
    assert same_task.done()
    assert metrics.memory_diagnostics_task is None
    assert calls >= 2
    assert maximum_active == 1


@pytest.mark.asyncio
async def test_memory_diagnostics_failure_keeps_scrape_available_and_labels_bounded(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LIYAN_MEMORY_DIAGNOSTICS", "true")
    metrics = PlatformMetrics()

    def failing_collector(_loop):
        raise RuntimeError("controlled diagnostic failure")

    monkeypatch.setattr(metrics, "_collect_memory_diagnostics", failing_collector, raising=False)

    await metrics.run_memory_diagnostics_once()
    rendered = metrics.render().decode("utf-8")

    assert 'metric="sample_success"} 0.0' in rendered
    assert 'metric="sample_stale"} 1.0' in rendered
    assert "tenant" not in rendered
    assert "subject" not in rendered
    assert "cursor" not in rendered


@pytest.mark.asyncio
async def test_memory_diagnostics_discard_unapproved_metric_and_stage_labels(monkeypatch) -> None:
    monkeypatch.setenv("LIYAN_MEMORY_DIAGNOSTICS", "true")
    metrics = PlatformMetrics()
    result = {
        "values": {
            "tasks": 3,
            "tenant-secret-value": 99,
        },
        "task_names": (),
        "object_types": (),
        "top_allocations": (),
        "stage_durations": (
            ("total", 0.01),
            ("subject-secret-value", 4.0),
        ),
    }
    monkeypatch.setattr(metrics, "_collect_memory_diagnostics", lambda _tasks: result)

    await metrics.run_memory_diagnostics_once()
    rendered = metrics.render().decode("utf-8")

    assert 'metric="tasks"} 3.0' in rendered
    assert 'stage="total"} 0.01' in rendered
    assert "tenant-secret-value" not in rendered
    assert "subject-secret-value" not in rendered


@pytest.mark.asyncio
async def test_memory_diagnostics_failure_retains_last_completed_sample(monkeypatch) -> None:
    monkeypatch.setenv("LIYAN_MEMORY_DIAGNOSTICS", "true")
    metrics = PlatformMetrics()
    result = {
        "values": {"tracemalloc_current_bytes": 123},
        "task_names": (),
        "object_types": (),
        "top_allocations": (),
        "stage_durations": (("total", 0.01),),
    }
    monkeypatch.setattr(metrics, "_collect_memory_diagnostics", lambda _tasks: result)
    await metrics.run_memory_diagnostics_once()

    def failing_collector(_tasks):
        raise RuntimeError("controlled diagnostic failure")

    monkeypatch.setattr(metrics, "_collect_memory_diagnostics", failing_collector)
    await metrics.run_memory_diagnostics_once()
    rendered = metrics.render().decode("utf-8")

    assert 'metric="tracemalloc_current_bytes"} 123.0' in rendered
    assert 'metric="sample_success"} 0.0' in rendered
    assert 'metric="sample_stale"} 1.0' in rendered
    assert 'stage="total"} 0.01' in rendered


@pytest.mark.asyncio
async def test_memory_diagnostics_close_waits_for_inflight_worker(monkeypatch) -> None:
    monkeypatch.setenv("LIYAN_MEMORY_DIAGNOSTICS", "true")
    metrics = PlatformMetrics()
    started = threading.Event()
    release = threading.Event()

    def controlled_collector(_tasks):
        started.set()
        assert release.wait(1.0)
        return {
            "values": {},
            "task_names": (),
            "object_types": (),
            "top_allocations": (),
            "stage_durations": (),
        }

    monkeypatch.setattr(metrics, "_collect_memory_diagnostics", controlled_collector)
    await metrics.start_memory_diagnostics()
    assert await asyncio.to_thread(started.wait, 0.5)

    close_task = asyncio.create_task(metrics.close())
    await asyncio.sleep(0.01)
    assert close_task.done() is False

    release.set()
    await asyncio.wait_for(close_task, timeout=0.5)
    rendered = metrics.render().decode("utf-8")

    assert metrics.memory_diagnostics_task is None
    assert 'metric="sample_running"} 0.0' in rendered
