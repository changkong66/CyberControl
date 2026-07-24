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
    encode_sse_frame,
    make_text_chunks,
    split_utf8_safely,
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


def test_split_utf8_handles_empty_text_and_rejects_tiny_chunks() -> None:
    assert split_utf8_safely("", 4) == [""]
    with pytest.raises(ValueError, match="at least four"):
        split_utf8_safely("abc", 3)


def test_encode_sse_frame_preserves_multiline_json_payload() -> None:
    event = SSEEvent(
        tenant_id="tenant-a",
        sequence=7,
        event_type="topic4.gate-c.probe",
        data={"message": "line-1\nline-2", "value": 3},
        emitted_at=datetime.now(UTC),
    )

    frame = encode_sse_frame(event, "signed-cursor").decode("utf-8")

    assert frame.startswith("id: signed-cursor\nevent: topic4.gate-c.probe\n")
    assert "data: " in frame
    assert frame.endswith("\n\n")


def test_chunk_assembler_rejects_duplicate_index_and_late_fragments() -> None:
    stream_id = uuid4()
    candidate_id = uuid4()
    chunks = make_text_chunks(
        "abcdef",
        stream_id=stream_id,
        candidate_id=candidate_id,
        candidate_version=1,
        block_id=None,
        max_bytes=4,
    )
    assembler = SSEChunkAssembler()
    assert assembler.add(chunks[0]) is True

    conflicting = chunks[0].model_copy(
        update={
            "fragment_id": uuid4(),
            "data": "zzzz",
            "data_sha256": "0" * 64,
        }
    )
    with pytest.raises(LiyanError) as conflict:
        assembler.add(conflicting)
    assert conflict.value.code == ErrorCode.SSE_FRAGMENT_CONFLICT

    for chunk in chunks[1:]:
        assembler.add(chunk)
    late_fragment = chunks[-1].model_copy(
        update={
            "chunk_index": len(chunks),
            "fragment_id": uuid4(),
            "data": "late",
            "data_sha256": "1" * 64,
        }
    )
    with pytest.raises(LiyanError) as closed:
        assembler.add(late_fragment)
    assert closed.value.code == ErrorCode.SSE_STREAM_CLOSED


def test_chunk_assembler_rejects_unbounded_gaps_and_incomplete_reads() -> None:
    stream_id = uuid4()
    candidate_id = uuid4()
    chunks = make_text_chunks(
        "abcdefghijklmnop",
        stream_id=stream_id,
        candidate_id=candidate_id,
        candidate_version=1,
        block_id="block-a",
        max_bytes=4,
    )
    assembler = SSEChunkAssembler(max_gap_buffer=1)
    assembler.add(chunks[2])
    with pytest.raises(LiyanError) as full:
        assembler.add(chunks[3])
    assert full.value.code == ErrorCode.MESSAGE_BUFFER_FULL

    with pytest.raises(LiyanError) as incomplete:
        assembler.assembled_text(
            stream_id=stream_id,
            candidate_id=candidate_id,
            candidate_version=1,
            block_id="block-a",
        )
    assert incomplete.value.code == ErrorCode.MESSAGE_SEQUENCE_GAP


@pytest.mark.asyncio
async def test_replay_log_retention_gap_and_latest_sequence() -> None:
    with pytest.raises(ValueError, match="capacity"):
        InMemorySSEReplayLog(capacity_per_tenant=0)
    with pytest.raises(ValueError, match="max_event_bytes"):
        InMemorySSEReplayLog(max_event_bytes=0)

    log = InMemorySSEReplayLog(capacity_per_tenant=1)
    assert await log.latest_sequence("tenant-a") is None
    await log.append("tenant-a", "progress", {"value": 1})
    second = await log.append("tenant-a", "progress", {"value": 2})
    assert await log.latest_sequence("tenant-a") == second.sequence
    with pytest.raises(LiyanError) as retained:
        await log.replay("tenant-a", -1)
    assert retained.value.code == ErrorCode.SSE_REPLAY_CURSOR_INVALID


@pytest.mark.asyncio
async def test_broker_rejects_invalid_subscription_inputs() -> None:
    with pytest.raises(ValueError, match="queue"):
        SSEBroker(InMemorySSEReplayLog(), subscriber_queue_size=0)

    broker = SSEBroker(InMemorySSEReplayLog())
    with pytest.raises(ValueError, match="through_sequence"):
        await broker.synchronize("tenant-a", through_sequence=-1)

    stream = broker.subscribe("tenant-a", after_sequence=-1)
    with pytest.raises(ValueError, match="after_sequence"):
        await anext(stream)
    await stream.aclose()

    stream = broker.subscribe("tenant-a", heartbeat_seconds=0)
    with pytest.raises(ValueError, match="heartbeat"):
        await anext(stream)
    await stream.aclose()


@pytest.mark.asyncio
async def test_broker_reports_active_tenants_and_backpressure_drop() -> None:
    broker = SSEBroker(InMemorySSEReplayLog(), subscriber_queue_size=1)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=1)
    waiting = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    assert broker.active_tenants() == ("tenant-a",)

    first = await broker.publish("tenant-a", "progress", {"value": 1})
    assert await waiting == first
    second = await broker.publish("tenant-a", "progress", {"value": 2})
    third = await broker.publish("tenant-a", "progress", {"value": 3})

    assert second.sequence == 1
    assert third.sequence == 2
    assert broker.active_tenants() == ()
    await stream.aclose()


@pytest.mark.asyncio
async def test_broker_retention_gap_closes_subscribers() -> None:
    log = InMemorySSEReplayLog(capacity_per_tenant=1)
    broker = SSEBroker(log)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=1)
    waiting = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    await log.append("tenant-a", "progress", {"value": 1})
    event = await log.append("tenant-a", "progress", {"value": 2})

    assert await broker.deliver(event) == 0
    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
    assert broker.active_tenants() == ()
    await stream.aclose()


@pytest.mark.asyncio
async def test_broker_missing_durable_sequence_is_retriable() -> None:
    class MissingReplayLog(InMemorySSEReplayLog):
        async def replay(self, tenant_id, after_sequence):
            del tenant_id, after_sequence
            return []

    broker = SSEBroker(MissingReplayLog())
    stream = broker.subscribe("tenant-a", heartbeat_seconds=1)
    waiting = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)

    with pytest.raises(LiyanError) as error:
        await broker.deliver(
            SSEEvent(
                tenant_id="tenant-a",
                sequence=2,
                event_type="progress",
                data={},
                emitted_at=datetime.now(UTC),
            )
        )
    assert error.value.code == ErrorCode.MESSAGE_SEQUENCE_GAP
    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
    await stream.aclose()
