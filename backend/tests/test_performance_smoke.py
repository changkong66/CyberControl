from __future__ import annotations

import asyncio
from time import perf_counter

import pytest

from liyans.infrastructure.messaging.bus import AsyncMessageBus, DispatchStatus
from liyans.infrastructure.streaming.sse import InMemorySSEReplayLog, SSEBroker


@pytest.mark.asyncio
async def test_sse_fanout_performance_and_ordering_smoke() -> None:
    subscriber_count = 32
    event_count = 64
    broker = SSEBroker(
        InMemorySSEReplayLog(capacity_per_tenant=event_count),
        subscriber_queue_size=event_count,
    )
    streams = [
        broker.subscribe("tenant-performance", heartbeat_seconds=5)
        for _index in range(subscriber_count)
    ]

    async def consume(stream) -> list[int]:
        received: list[int] = []
        async for event in stream:
            if event is None:
                continue
            received.append(event.sequence)
            if len(received) == event_count:
                return received
        return received

    consumers = [asyncio.create_task(consume(stream)) for stream in streams]
    for _attempt in range(100):
        if len(broker.active_tenants()) == 1:
            break
        await asyncio.sleep(0.001)
    else:
        pytest.fail("SSE performance subscribers did not become active")

    started = perf_counter()
    for sequence in range(event_count):
        await broker.publish(
            "tenant-performance",
            "generation.progress",
            {"sequence": sequence},
        )
    received = await asyncio.wait_for(asyncio.gather(*consumers), timeout=10)
    elapsed = perf_counter() - started

    assert all(sequences == list(range(event_count)) for sequences in received)
    assert elapsed < 10
    for stream in streams:
        await stream.aclose()


@pytest.mark.asyncio
async def test_message_bus_parallel_partition_performance_smoke(make_envelope) -> None:
    partition_count = 32
    events_per_partition = 16
    bus = AsyncMessageBus()
    handled = 0

    async def handler(_envelope) -> None:
        nonlocal handled
        handled += 1

    bus.register("topic3.test.event", handler)

    async def publish_partition(partition_index: int) -> None:
        for sequence in range(events_per_partition):
            envelope = make_envelope(
                sequence,
                tenant_id=f"tenant-{partition_index}",
            )
            result = await bus.publish(envelope)
            assert result.status == DispatchStatus.PROCESSED

    started = perf_counter()
    await asyncio.wait_for(
        asyncio.gather(*(publish_partition(index) for index in range(partition_count))),
        timeout=10,
    )
    elapsed = perf_counter() - started

    assert handled == partition_count * events_per_partition
    assert elapsed < 10
