from __future__ import annotations

import pytest

from liyans.core.errors import RateLimitExceeded
from liyans.infrastructure.tasks.queue import AsyncTaskQueue, TaskPriority, TaskRequest


@pytest.mark.asyncio
async def test_task_queue_retries_retriable_failure() -> None:
    queue = AsyncTaskQueue(worker_count=1)
    calls = 0

    async def handler(request) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RateLimitExceeded(0.001)
        return {"ok": request.payload["value"]}

    queue.register("retryable", handler)
    await queue.start()
    result = await queue.submit(
        TaskRequest(
            task_type="retryable",
            tenant_id="tenant-a",
            payload={"value": 7},
            max_attempts=2,
        )
    )
    await queue.close()
    assert result.succeeded is True
    assert result.attempts == 2
    assert result.output == {"ok": 7}


@pytest.mark.asyncio
async def test_task_priority_and_final_compensation() -> None:
    queue = AsyncTaskQueue(worker_count=1)
    order: list[str] = []
    compensated: list[str] = []

    async def handler(request) -> dict:
        order.append(request.payload["name"])
        if request.payload.get("fail"):
            raise RuntimeError("injected")
        return {}

    async def compensate(request, exc) -> None:
        del exc
        compensated.append(request.payload["name"])

    queue.register("ordered", handler, compensation=compensate)
    low = await queue.enqueue(
        TaskRequest(
            task_type="ordered",
            tenant_id="tenant-a",
            payload={"name": "low"},
            priority=TaskPriority.LOW,
        )
    )
    high = await queue.enqueue(
        TaskRequest(
            task_type="ordered",
            tenant_id="tenant-a",
            payload={"name": "high", "fail": True},
            priority=TaskPriority.HIGH,
        )
    )
    await queue.start()
    high_result, low_result = await high, await low
    await queue.close()
    assert order == ["high", "low"]
    assert high_result.succeeded is False
    assert low_result.succeeded is True
    assert compensated == ["high"]
