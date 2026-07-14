from __future__ import annotations

import pytest

from liyans.core.errors import ErrorCode, LiyanError
from liyans.infrastructure.messaging.bus import AsyncMessageBus, DispatchStatus


@pytest.mark.asyncio
async def test_bus_buffers_gaps_and_drains_in_partition_order(make_envelope) -> None:
    observed: list[int] = []
    bus = AsyncMessageBus()

    async def handler(envelope) -> None:
        observed.append(envelope.sequence)

    bus.register("topic3.test.event", handler)
    buffered = await bus.publish(make_envelope(1))
    processed = await bus.publish(make_envelope(0))

    assert buffered.status == DispatchStatus.BUFFERED
    assert processed.next_expected_sequence == 2
    assert observed == [0, 1]


@pytest.mark.asyncio
async def test_bus_deduplicates_and_rejects_digest_conflict(make_envelope) -> None:
    bus = AsyncMessageBus()
    calls = 0

    async def handler(envelope) -> None:
        nonlocal calls
        calls += 1

    bus.register("topic3.test.event", handler)
    envelope = make_envelope(0, idempotency_key="same-key:000000000000")
    await bus.publish(envelope)
    duplicate = await bus.publish(envelope)
    assert duplicate.status == DispatchStatus.DUPLICATE
    assert calls == 1

    conflicting = envelope.model_copy(update={"payload": {"different": True}})
    with pytest.raises(LiyanError) as raised:
        await bus.publish(conflicting)
    assert raised.value.code == ErrorCode.MESSAGE_DUPLICATE_CONFLICT


@pytest.mark.asyncio
async def test_handler_failure_does_not_advance_partition_cursor(make_envelope) -> None:
    bus = AsyncMessageBus()
    attempts = 0

    async def handler(envelope) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected failure")

    bus.register("topic3.test.event", handler)
    envelope = make_envelope(0)
    with pytest.raises(RuntimeError):
        await bus.publish(envelope)
    retried = envelope.model_copy(
        update={"delivery": envelope.delivery.model_copy(update={"attempt": 2})}
    )
    result = await bus.publish(retried)
    assert result.status == DispatchStatus.PROCESSED
    assert result.next_expected_sequence == 1


@pytest.mark.asyncio
async def test_partition_cursor_is_scoped_by_tenant(make_envelope) -> None:
    observed: list[str] = []
    bus = AsyncMessageBus()

    async def handler(envelope) -> None:
        observed.append(envelope.tenant_id)

    bus.register("topic3.test.event", handler)
    first = make_envelope(0, tenant_id="tenant-a").model_copy(
        update={"partition_key": "shared-logical-partition"}
    )
    second = make_envelope(0, tenant_id="tenant-b").model_copy(
        update={"partition_key": "shared-logical-partition"}
    )

    first_result = await bus.publish(first)
    second_result = await bus.publish(second)

    assert first_result.next_expected_sequence == 1
    assert second_result.next_expected_sequence == 1
    assert observed == ["tenant-a", "tenant-b"]


@pytest.mark.asyncio
async def test_duplicate_buffered_message_is_not_reported_as_completed(make_envelope) -> None:
    bus = AsyncMessageBus()

    async def handler(_envelope) -> None:
        return None

    bus.register("topic3.test.event", handler)
    envelope = make_envelope(1)

    first = await bus.publish(envelope)
    duplicate = await bus.publish(envelope)

    assert first.status == DispatchStatus.BUFFERED
    assert duplicate.status == DispatchStatus.IN_FLIGHT
