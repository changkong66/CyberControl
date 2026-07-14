from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from liyans.core.errors import ErrorCode, LiyanError
from liyans.infrastructure.streaming.sse import (
    InMemorySSEReplayLog,
    ReplayCursorCodec,
    SSEBroker,
    SSEChunkAssembler,
    SSEEvent,
    make_text_chunks,
)


def test_utf8_chunks_reassemble_after_out_of_order_delivery() -> None:
    stream_id = uuid4()
    candidate_id = uuid4()
    chunks = make_text_chunks(
        "控制系统稳定性",
        stream_id=stream_id,
        candidate_id=candidate_id,
        candidate_version=1,
        block_id="block-1",
        max_bytes=6,
    )
    assert len(chunks) > 2
    assert all(len(chunk.data.encode("utf-8")) <= 6 for chunk in chunks)

    assembler = SSEChunkAssembler()
    assembler.add(chunks[1])
    assembler.add(chunks[0])
    for chunk in chunks[2:]:
        assembler.add(chunk)
    assert (
        assembler.assembled_text(
            stream_id=stream_id,
            candidate_id=candidate_id,
            candidate_version=1,
            block_id="block-1",
        )
        == "控制系统稳定性"
    )


def test_chunk_contract_rejects_tampered_digest() -> None:
    chunk = make_text_chunks(
        "abc",
        stream_id=uuid4(),
        candidate_id=uuid4(),
        candidate_version=1,
        block_id=None,
    )[0]
    with pytest.raises(ValidationError):
        chunk.model_copy(update={"data": "changed"}).model_validate(
            {**chunk.model_dump(), "data": "changed"}
        )


@pytest.mark.asyncio
async def test_signed_cursor_is_tenant_bound_and_replay_is_monotonic() -> None:
    codec = ReplayCursorCodec(b"x" * 32)
    log = InMemorySSEReplayLog(capacity_per_tenant=4)
    broker = SSEBroker(log)
    first = await broker.publish("tenant-a", "progress", {"value": 1})
    second = await broker.publish("tenant-a", "progress", {"value": 2})
    cursor = codec.encode("tenant-a", first.sequence)
    assert codec.decode(cursor, "tenant-a") == first.sequence
    with pytest.raises(LiyanError):
        codec.decode(cursor, "tenant-b")
    replay = await log.replay("tenant-a", first.sequence)
    assert [event.sequence for event in replay] == [second.sequence]


@pytest.mark.asyncio
async def test_broker_deduplicates_local_and_notification_delivery() -> None:
    broker = SSEBroker(InMemorySSEReplayLog(), subscriber_queue_size=4)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=0.01)
    waiting = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)

    event = await broker.publish("tenant-a", "progress", {"value": 1})
    assert await waiting == event
    assert await broker.deliver(event) == 0
    assert await anext(stream) is None
    await stream.aclose()


@pytest.mark.asyncio
async def test_broker_replays_missing_sequence_before_notified_event() -> None:
    log = InMemorySSEReplayLog()
    broker = SSEBroker(log, subscriber_queue_size=4)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=1)
    waiting = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)

    first = await log.append("tenant-a", "progress", {"value": 1})
    second = await log.append("tenant-a", "progress", {"value": 2})
    delivered = await broker.deliver(second)

    assert delivered == 2
    assert await waiting == first
    assert await anext(stream) == second
    await stream.aclose()


@pytest.mark.asyncio
async def test_broker_rejects_cross_tenant_replay_data() -> None:
    class InvalidReplayLog(InMemorySSEReplayLog):
        async def replay(self, tenant_id, after_sequence):
            del tenant_id
            if after_sequence is None:
                return []
            return [
                SSEEvent(
                    tenant_id="other-tenant",
                    sequence=0,
                    event_type="progress",
                    data={},
                    emitted_at=datetime.now(UTC),
                )
            ]

    broker = SSEBroker(InvalidReplayLog())
    stream = broker.subscribe("tenant-a")
    waiting = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    with pytest.raises(ValueError, match="another tenant"):
        await broker.deliver(
            SSEEvent(
                tenant_id="tenant-a",
                sequence=1,
                event_type="progress",
                data={},
                emitted_at=datetime.now(UTC),
            )
        )
    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
    await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "data", "max_event_bytes"),
    [
        ("invalid event type", {}, 1024),
        ("progress", {"value": float("nan")}, 1024),
        ("progress", {"value": "x" * 128}, 16),
    ],
)
async def test_sse_log_rejects_invalid_or_oversized_events(
    event_type,
    data,
    max_event_bytes,
) -> None:
    log = InMemorySSEReplayLog(max_event_bytes=max_event_bytes)

    with pytest.raises(LiyanError) as error:
        await log.append("tenant-a", event_type, data)

    assert error.value.code == ErrorCode.SSE_EVENT_INVALID
