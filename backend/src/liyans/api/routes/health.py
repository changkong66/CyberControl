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
    auth_configured = request.app.state.auth_configured
    ready_status = (
        database.healthy and task_queue.running and not message_bus.closed and auth_configured
    )
    if not ready_status:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
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
        "config_digest": request.app.state.provider_config.snapshot.digest,
    }
