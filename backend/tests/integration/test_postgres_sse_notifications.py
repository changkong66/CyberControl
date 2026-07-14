from __future__ import annotations

import asyncio
import os

import pytest

from liyans.core.tenant import tenant_scope
from liyans.infrastructure.streaming import (
    PostgresSSENotificationBridge,
    PostgresSSEReplayLog,
    SSEBroker,
)

pytestmark = pytest.mark.integration
RUNTIME_URL = os.getenv("LIYAN_TEST_DATABASE_URL")


@pytest.mark.asyncio
async def test_two_instances_receive_once_and_recover_disconnect_gap(
    postgres_runtime,
) -> None:
    if not RUNTIME_URL:
        pytest.skip("PostgreSQL runtime integration URL is not configured")
    database, _migrator, context = postgres_runtime
    broker_a = SSEBroker(PostgresSSEReplayLog(database), subscriber_queue_size=16)
    broker_b = SSEBroker(PostgresSSEReplayLog(database), subscriber_queue_size=16)
    bridge_a = PostgresSSENotificationBridge(
        RUNTIME_URL,
        broker_a,
        reconnect_base_seconds=0.01,
        reconnect_max_seconds=0.05,
        startup_timeout_seconds=2,
    )
    bridge_b = PostgresSSENotificationBridge(
        RUNTIME_URL,
        broker_b,
        reconnect_base_seconds=0.01,
        reconnect_max_seconds=0.05,
        startup_timeout_seconds=2,
    )
    await bridge_a.start()
    await bridge_b.start()

    stream_a = broker_a.subscribe(context.tenant_id, heartbeat_seconds=1)
    stream_b = broker_b.subscribe(context.tenant_id, heartbeat_seconds=1)
    with tenant_scope(context):
        first_from_a = asyncio.create_task(anext(stream_a))
        first_from_b = asyncio.create_task(anext(stream_b))
    for _attempt in range(100):
        if (
            context.tenant_id in broker_a.active_tenants()
            and context.tenant_id in broker_b.active_tenants()
        ):
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("SSE subscribers did not become active")

    try:
        with tenant_scope(context):
            persisted = await broker_a.publish(
                context.tenant_id,
                "generation.progress",
                {"progress": 10},
            )
        received_a, received_b = await asyncio.gather(
            asyncio.wait_for(first_from_a, timeout=2),
            asyncio.wait_for(first_from_b, timeout=2),
        )
        assert received_a is not None and received_b is not None
        assert received_a.sequence == persisted.sequence
        assert received_b.sequence == persisted.sequence

        with tenant_scope(context):
            no_duplicate = await asyncio.wait_for(anext(stream_a), timeout=2)
        assert no_duplicate is None

        await bridge_b.close()
        with tenant_scope(context):
            missed_one = await broker_a.publish(
                context.tenant_id,
                "generation.progress",
                {"progress": 50},
            )
            missed_two = await broker_a.publish(
                context.tenant_id,
                "generation.completed",
                {"progress": 100},
            )

        await bridge_b.start()
        with tenant_scope(context):
            recovered_one = await asyncio.wait_for(anext(stream_b), timeout=2)
            recovered_two = await asyncio.wait_for(anext(stream_b), timeout=2)
        assert recovered_one is not None and recovered_two is not None
        assert [recovered_one.sequence, recovered_two.sequence] == [
            missed_one.sequence,
            missed_two.sequence,
        ]
    finally:
        first_from_a.cancel()
        first_from_b.cancel()
        await asyncio.gather(first_from_a, first_from_b, return_exceptions=True)
        await stream_a.aclose()
        await stream_b.aclose()
        await bridge_a.close()
        await bridge_b.close()
