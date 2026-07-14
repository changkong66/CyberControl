from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/ready")
async def ready(request: Request) -> dict[str, object]:
    provider_policy = request.app.state.provider_policy
    task_queue = request.app.state.task_queue
    message_bus = request.app.state.message_bus
    return {
        "status": "ready",
        "provider_policy_version": provider_policy.policy_version,
        "enabled_external_providers": provider_policy.enabled_external_aliases(),
        "task_queue_running": task_queue.running,
        "message_bus_open": not message_bus.closed,
        "config_digest": request.app.state.provider_config.snapshot.digest,
    }
