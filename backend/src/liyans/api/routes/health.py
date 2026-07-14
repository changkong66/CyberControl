from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict[str, object]:
    provider_policy = request.app.state.provider_policy
    task_queue = request.app.state.task_queue
    message_bus = request.app.state.message_bus
    database = await request.app.state.database_health.check()
    metrics = request.app.state.metrics
    metrics.observe_database_health(healthy=database.healthy, latency_ms=database.latency_ms)
    auth_configured = request.app.state.auth_configured
    publisher = request.app.state.outbox_publisher
    publisher_ready = publisher is None or publisher.healthy
    bridge = request.app.state.sse_notification_bridge
    bridge_ready = bridge is None or (bridge.running and bridge.connected)
    ready_status = (
        database.healthy
        and task_queue.running
        and not message_bus.closed
        and auth_configured
        and publisher_ready
        and bridge_ready
    )
    if not ready_status:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    metrics.set_component_ready("task_queue", task_queue.running)
    metrics.set_component_ready("message_bus", not message_bus.closed)
    metrics.set_component_ready("authentication", auth_configured)
    metrics.set_component_ready("outbox_publisher", publisher_ready)
    metrics.set_component_ready("sse_notification_bridge", bridge_ready)
    return {
        "status": "ready" if ready_status else "degraded",
        "database": {
            "status": "up" if database.healthy else "down",
            "latency_ms": round(database.latency_ms, 3),
        },
        "authentication": "configured" if auth_configured else "unconfigured",
        "provider_policy_version": provider_policy.policy_version,
        "enabled_external_providers": provider_policy.enabled_external_aliases(),
        "task_queue_running": task_queue.running,
        "message_bus_open": not message_bus.closed,
        "outbox_publisher": (
            "healthy"
            if publisher is not None and publisher.healthy
            else "degraded"
            if publisher is not None
            else "disabled"
        ),
        "sse_notification_bridge": (
            "connected" if bridge is not None and bridge.connected else "disabled"
        ),
        "config_digest": request.app.state.provider_config.snapshot.digest,
    }
