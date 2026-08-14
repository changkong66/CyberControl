from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

import liyans.infrastructure.streaming.sse as sse_module
from liyans.api.streaming import OwnedStreamingResponse, TenantScopedSSEStream
from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.infrastructure.observability.metrics import PlatformMetrics
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


async def _wait_for_live_subscription(broker: SSEBroker, tenant_id: str = "tenant-a") -> None:
    for _attempt in range(100):
        subscribers = broker._subscribers.get(tenant_id, set())
        if any(not subscriber.closed and subscriber.state == "LIVE" for subscriber in subscribers):
            return
        await asyncio.sleep(0)
    pytest.fail("SSE subscriber did not become live")


def _event(
    sequence: int,
    *,
    tenant_id: str = "tenant-a",
    value: int | str | None = None,
    event_type: str = "progress",
) -> SSEEvent:
    return SSEEvent(
        tenant_id=tenant_id,
        sequence=sequence,
        event_type=event_type,
        data={"value": sequence if value is None else value},
        emitted_at=datetime.now(UTC),
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
async def test_broker_persist_does_not_block_on_live_fanout() -> None:
    broker = SSEBroker(InMemorySSEReplayLog(), subscriber_queue_size=4)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=60)
    waiting = asyncio.create_task(anext(stream))
    await _wait_for_live_subscription(broker)

    event = await broker.persist("tenant-a", "progress", {"value": 1})
    await asyncio.sleep(0)

    assert waiting.done() is False
    await broker.deliver(event)
    assert await waiting == event
    await stream.aclose()


@pytest.mark.asyncio
async def test_broker_closes_subscriber_when_replay_consumer_is_closed() -> None:
    log = InMemorySSEReplayLog()
    replayed = await log.append("tenant-a", "progress", {"value": 1})
    broker = SSEBroker(log)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=60)

    assert await anext(stream) == replayed
    assert broker.active_tenants() == ("tenant-a",)

    await stream.aclose()

    assert broker.active_tenants() == ()


@pytest.mark.asyncio
async def test_broker_coalesces_identical_subscription_replay_queries() -> None:
    class CountingReplayLog(InMemorySSEReplayLog):
        def __init__(self) -> None:
            super().__init__()
            self.replay_calls = 0
            self.latest_calls = 0

        async def replay(self, tenant_id, after_sequence):
            self.replay_calls += 1
            return await super().replay(tenant_id, after_sequence)

        async def latest_sequence(self, tenant_id):
            self.latest_calls += 1
            return await super().latest_sequence(tenant_id)

    class CoordinatedBroker(SSEBroker):
        def __init__(self, replay_log) -> None:
            super().__init__(replay_log, replay_cache_seconds=0.01)
            self.replay_arrivals = 0
            self.both_replays_arrived = asyncio.Event()
            self.release_replay = asyncio.Event()

        async def _coalesced_replay(
            self,
            tenant_id,
            after_sequence,
            *,
            through_sequence,
        ):
            self.replay_arrivals += 1
            if self.replay_arrivals == 2:
                self.both_replays_arrived.set()
            await self.both_replays_arrived.wait()
            result = await super()._coalesced_replay(
                tenant_id,
                after_sequence,
                through_sequence=through_sequence,
            )
            await self.release_replay.wait()
            return result

    log = CountingReplayLog()
    event = await log.append("tenant-a", "progress", {"value": 1})
    broker = CoordinatedBroker(log)
    first = broker.subscribe("tenant-a", heartbeat_seconds=60)
    second = broker.subscribe("tenant-a", heartbeat_seconds=60)

    first_event = asyncio.create_task(anext(first))
    second_event = asyncio.create_task(anext(second))
    await broker.both_replays_arrived.wait()
    broker.release_replay.set()

    assert await first_event == event
    assert await second_event == event
    assert log.replay_calls == 1
    assert log.latest_calls == 1

    await first.aclose()
    await second.aclose()
    await asyncio.sleep(0.02)
    third = broker.subscribe("tenant-a", heartbeat_seconds=60)
    assert await anext(third) == event
    assert log.replay_calls == 2
    assert log.latest_calls == 2
    await third.aclose()


@pytest.mark.asyncio
async def test_broker_coalesces_two_thousand_same_tenant_admissions() -> None:
    class CoordinatedReplayLog(InMemorySSEReplayLog):
        def __init__(self) -> None:
            super().__init__()
            self.latest_calls = 0
            self.replay_calls = 0
            self.latest_started = asyncio.Event()
            self.replay_started = asyncio.Event()
            self.release_latest = asyncio.Event()
            self.release_replay = asyncio.Event()

        async def latest_sequence(self, tenant_id):
            self.latest_calls += 1
            self.latest_started.set()
            await self.release_latest.wait()
            return await super().latest_sequence(tenant_id)

        async def replay(self, tenant_id, after_sequence):
            self.replay_calls += 1
            self.replay_started.set()
            await self.release_replay.wait()
            return await super().replay(tenant_id, after_sequence)

    log = CoordinatedReplayLog()
    event = await log.append("tenant-a", "progress", {"value": 1})
    broker = SSEBroker(log)
    streams = [broker.subscribe("tenant-a", heartbeat_seconds=60) for _ in range(2_000)]
    admissions = [asyncio.create_task(anext(stream)) for stream in streams]

    await asyncio.wait_for(log.latest_started.wait(), timeout=1)
    for _attempt in range(200):
        if len(broker._subscribers["tenant-a"]) == 2_000:
            break
        await asyncio.sleep(0)
    else:
        pytest.fail("2,000 SSE subscriptions did not reach coordinated admission")

    log.release_latest.set()
    await asyncio.wait_for(log.replay_started.wait(), timeout=1)
    log.release_replay.set()

    assert await asyncio.gather(*admissions) == [event] * 2_000
    assert log.latest_calls == 1
    assert log.replay_calls == 1

    await asyncio.gather(*(stream.aclose() for stream in streams))
    assert broker.active_tenants() == ()


@pytest.mark.asyncio
async def test_broker_does_not_share_replay_across_different_durable_watermarks() -> None:
    class SnapshotReplayLog(InMemorySSEReplayLog):
        def __init__(self) -> None:
            super().__init__()
            self.replay_calls = 0
            self.first_replay_captured = asyncio.Event()
            self.release_first_replay = asyncio.Event()

        async def replay(self, tenant_id, after_sequence):
            replay = await super().replay(tenant_id, after_sequence)
            self.replay_calls += 1
            if self.replay_calls == 1:
                self.first_replay_captured.set()
                await self.release_first_replay.wait()
            return replay

    log = SnapshotReplayLog()
    baseline = await log.append("tenant-a", "progress", {"value": 0})
    broker = SSEBroker(log, replay_cache_seconds=60)
    first = broker.subscribe(
        "tenant-a",
        after_sequence=baseline.sequence,
        heartbeat_seconds=1,
    )
    first_waiting = asyncio.create_task(anext(first))
    await log.first_replay_captured.wait()

    committed = await log.append("tenant-a", "progress", {"value": 1})
    assert await broker.deliver(committed) == 0
    second = broker.subscribe(
        "tenant-a",
        after_sequence=baseline.sequence,
        heartbeat_seconds=1,
    )
    assert await anext(second) == committed

    log.release_first_replay.set()
    assert await first_waiting == committed
    assert log.replay_calls == 2
    assert broker._replay_cache["tenant-a"][baseline.sequence].events == (committed,)

    await first.aclose()
    await second.aclose()


@pytest.mark.asyncio
async def test_broker_invalidates_subscription_replay_cache_after_publish() -> None:
    log = InMemorySSEReplayLog()
    first_event = await log.append("tenant-a", "progress", {"value": 1})
    broker = SSEBroker(log, replay_cache_seconds=60)
    first = broker.subscribe("tenant-a", heartbeat_seconds=60)
    assert await anext(first) == first_event

    second_event = await broker.publish("tenant-a", "progress", {"value": 2})
    second = broker.subscribe("tenant-a", heartbeat_seconds=60)

    assert await anext(second) == first_event
    assert await anext(second) == second_event

    await first.aclose()
    await second.aclose()


@pytest.mark.asyncio
async def test_broker_bounds_subscription_replay_cache_per_tenant() -> None:
    class EmptyReplayLog(InMemorySSEReplayLog):
        async def replay(self, tenant_id, after_sequence):
            del tenant_id, after_sequence
            return []

    broker = SSEBroker(EmptyReplayLog(), replay_cache_seconds=60)
    streams = [
        broker.subscribe("tenant-a", after_sequence=sequence, heartbeat_seconds=0.001)
        for sequence in range(9)
    ]

    assert await asyncio.gather(*(anext(stream) for stream in streams)) == [None] * 9
    assert len(broker._replay_cache["tenant-a"]) == 8

    await asyncio.gather(*(stream.aclose() for stream in streams))


@pytest.mark.asyncio
async def test_broker_uses_latest_sequence_when_initial_replay_is_empty() -> None:
    class LatestOnlyReplayLog(InMemorySSEReplayLog):
        async def replay(self, tenant_id, after_sequence):
            del tenant_id, after_sequence
            return []

        async def latest_sequence(self, tenant_id):
            assert tenant_id == "tenant-a"
            return 5

    broker = SSEBroker(LatestOnlyReplayLog())
    stream = broker.subscribe("tenant-a", heartbeat_seconds=0.001)

    assert await anext(stream) is None
    subscriber = next(iter(broker._subscribers["tenant-a"]))
    assert subscriber.last_sequence == 5
    await stream.aclose()


@pytest.mark.asyncio
async def test_broker_live_wait_cancellation_removes_subscriber() -> None:
    broker = SSEBroker(InMemorySSEReplayLog())
    stream = broker.subscribe("tenant-a", heartbeat_seconds=60)
    waiting = asyncio.create_task(anext(stream))
    for _attempt in range(100):
        if broker.active_tenants():
            break
        await asyncio.sleep(0)
    else:
        pytest.fail("SSE subscriber did not become active")

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting

    assert broker.active_tenants() == ()


@pytest.mark.asyncio
async def test_filtered_subscription_does_not_queue_unrelated_events() -> None:
    broker = SSEBroker(InMemorySSEReplayLog(), subscriber_queue_size=2)
    stream = broker.subscribe(
        "tenant-a",
        heartbeat_seconds=60,
        event_type_prefixes=("topic4.",),
    )
    waiting = asyncio.create_task(anext(stream))
    await _wait_for_live_subscription(broker)

    unrelated = _event(0, event_type="topic3.internal")
    relevant = _event(1, event_type="topic4.publication.committed")
    assert await broker.deliver(unrelated) == 0
    assert not waiting.done()
    assert await broker.deliver(relevant) == 1
    assert await waiting == relevant
    await stream.aclose()


@pytest.mark.asyncio
async def test_subscription_close_has_one_owner_when_cancel_and_close_race() -> None:
    metrics = PlatformMetrics()
    broker = SSEBroker(InMemorySSEReplayLog(), metrics=metrics)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=60)
    waiting = asyncio.create_task(anext(stream))
    await _wait_for_live_subscription(broker)

    close_task = asyncio.create_task(stream.aclose())
    waiting.cancel()
    await asyncio.gather(close_task, waiting, return_exceptions=True)

    assert broker.active_tenants() == ()
    assert stream._cleanup_complete is True
    rendered = metrics.render()
    assert b'metric="closing_subscriptions"' in rendered
    assert b'metric="closing_subscriptions"} 0.0' in rendered


@pytest.mark.asyncio
async def test_subscription_rejects_concurrent_advancement() -> None:
    broker = SSEBroker(InMemorySSEReplayLog())
    stream = broker.subscribe("tenant-a", heartbeat_seconds=60)
    waiting = asyncio.create_task(anext(stream))
    await _wait_for_live_subscription(broker)

    with pytest.raises(RuntimeError, match="advanced concurrently"):
        await anext(stream)

    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
    assert broker.active_tenants() == ()


@pytest.mark.asyncio
async def test_broker_retention_drop_wakes_live_waiter_immediately() -> None:
    log = InMemorySSEReplayLog(capacity_per_tenant=1)
    broker = SSEBroker(log)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=60)
    waiting = asyncio.create_task(anext(stream))
    await _wait_for_live_subscription(broker)

    await log.append("tenant-a", "progress", {"value": 1})
    newest = await log.append("tenant-a", "progress", {"value": 2})
    assert await broker.deliver(newest) == 0

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(waiting, timeout=0.1)
    assert broker.active_tenants() == ()


@pytest.mark.asyncio
async def test_broker_replays_missing_sequence_before_notified_event() -> None:
    log = InMemorySSEReplayLog()
    broker = SSEBroker(log, subscriber_queue_size=4)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=1)
    waiting = asyncio.create_task(anext(stream))
    await _wait_for_live_subscription(broker)

    first = await log.append("tenant-a", "progress", {"value": 1})
    second = await log.append("tenant-a", "progress", {"value": 2})
    delivered = await broker.deliver(second)

    assert delivered == 2
    assert await waiting == first
    assert await anext(stream) == second
    await stream.aclose()


@pytest.mark.asyncio
async def test_broker_buffers_live_events_during_subscription_replay_without_loss() -> None:
    class DelayedReplayLog(InMemorySSEReplayLog):
        def __init__(self) -> None:
            super().__init__()
            self.replay_started = asyncio.Event()
            self.release_replay = asyncio.Event()

        async def replay(self, tenant_id, after_sequence):
            self.replay_started.set()
            await self.release_replay.wait()
            return await super().replay(tenant_id, after_sequence)

    log = DelayedReplayLog()
    broker = SSEBroker(log, subscriber_queue_size=4)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=1)
    waiting = asyncio.create_task(anext(stream))

    await log.replay_started.wait()
    first = await log.append("tenant-a", "progress", {"value": 1})
    second = await log.append("tenant-a", "progress", {"value": 2})
    assert await broker.deliver(second) == 0
    log.release_replay.set()

    assert await waiting == first
    assert await anext(stream) == second
    assert await anext(stream) is None
    await stream.aclose()


@pytest.mark.asyncio
async def test_broker_merges_no_cursor_history_and_live_replay_without_gap() -> None:
    class DelayedReplayLog(InMemorySSEReplayLog):
        def __init__(self) -> None:
            super().__init__()
            self.replay_started = asyncio.Event()
            self.release_replay = asyncio.Event()

        async def replay(self, tenant_id, after_sequence):
            self.replay_started.set()
            await self.release_replay.wait()
            return await super().replay(tenant_id, after_sequence)

    log = DelayedReplayLog()
    first = await log.append("tenant-a", "progress", {"value": 1})
    second = await log.append("tenant-a", "progress", {"value": 2})
    broker = SSEBroker(log, subscriber_queue_size=8)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=0.01)
    waiting = asyncio.create_task(anext(stream))

    await log.replay_started.wait()
    third = await log.append("tenant-a", "progress", {"value": 3})
    fourth = await log.append("tenant-a", "progress", {"value": 4})
    assert await broker.deliver(fourth) == 0
    log.release_replay.set()

    assert [
        await waiting,
        await anext(stream),
        await anext(stream),
        await anext(stream),
    ] == [first, second, third, fourth]
    assert await anext(stream) is None
    await stream.aclose()


@pytest.mark.asyncio
async def test_duplicate_replay_drains_terminal_events_committed_during_history_delivery() -> None:
    log = InMemorySSEReplayLog(capacity_per_tenant=64)
    baseline = await log.append("tenant-a", "topic4.marker", {"ordinal": 0})
    history = [
        await log.append("tenant-a", "topic4.probe", {"ordinal": ordinal})
        for ordinal in range(1, 21)
    ]
    broker = SSEBroker(log, subscriber_queue_size=2)
    stream = broker.subscribe(
        "tenant-a",
        after_sequence=baseline.sequence,
        heartbeat_seconds=0.01,
        event_type_prefixes=("topic4.",),
    )

    assert await anext(stream) == history[0]
    terminal = [
        await log.append("tenant-a", "topic4.probe", {"ordinal": ordinal})
        for ordinal in range(21, 25)
    ]
    for event in terminal:
        assert await broker.deliver(event) == 0

    received = [history[0]]
    for _ in range(len(history) + len(terminal) - 1):
        received.append(await anext(stream))

    assert [event.sequence for event in received] == list(range(1, 25))
    assert len({event.sequence for event in received}) == 24
    assert stream.ready is True
    subscriber = next(iter(broker._subscribers["tenant-a"]))
    assert subscriber.state == "LIVE"
    assert subscriber.replay_buffer == {}
    assert subscriber.queue.empty()
    await stream.aclose()


@pytest.mark.asyncio
async def test_request_disconnect_during_replay_closes_subscription_owner() -> None:
    class BlockingReplayLog(InMemorySSEReplayLog):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()

        async def replay(self, tenant_id, after_sequence):
            del tenant_id, after_sequence
            self.started.set()
            await asyncio.Event().wait()

    class DisconnectingRequest:
        def __init__(self) -> None:
            self.disconnected = False

        async def is_disconnected(self) -> bool:
            return self.disconnected

    log = BlockingReplayLog()
    broker = SSEBroker(log)
    subscription = broker.subscribe("tenant-a", heartbeat_seconds=60)
    context = TenantContext(
        tenant_id="tenant-a",
        subject_ref="subject-a",
        roles=frozenset({"learner"}),
        scopes=frozenset({"topic4:sse:read"}),
        trace_id="0" * 32,
    )
    request = DisconnectingRequest()
    stream = TenantScopedSSEStream(request, subscription, context, object())
    stream._disconnect_poll_seconds = 0.001
    waiting = asyncio.create_task(anext(stream))

    await log.started.wait()
    request.disconnected = True

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(waiting, timeout=0.2)
    assert broker.active_tenants() == ()
    assert broker._replay_tasks == {}
    assert subscription._cleanup_complete is True


@pytest.mark.asyncio
async def test_broker_close_while_live_wait_is_pending_is_idempotent() -> None:
    broker = SSEBroker(InMemorySSEReplayLog())
    stream = broker.subscribe("tenant-a", heartbeat_seconds=60)
    waiting = asyncio.create_task(anext(stream))
    await _wait_for_live_subscription(broker)

    await stream.aclose()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(waiting, timeout=0.1)
    await stream.aclose()
    assert broker.active_tenants() == ()


@pytest.mark.asyncio
async def test_broker_close_finishes_shared_replay_cleanup_when_caller_is_cancelled() -> None:
    class CancellationAwareReplayLog(InMemorySSEReplayLog):
        def __init__(self) -> None:
            super().__init__()
            self.replay_started = asyncio.Event()
            self.replay_cancelled = asyncio.Event()
            self.release_cleanup = asyncio.Event()

        async def replay(self, tenant_id, after_sequence):
            del tenant_id, after_sequence
            self.replay_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.replay_cancelled.set()
                await self.release_cleanup.wait()
                raise

    log = CancellationAwareReplayLog()
    broker = SSEBroker(log)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=60)
    waiting = asyncio.create_task(anext(stream))
    await log.replay_started.wait()

    closing = asyncio.create_task(stream.aclose())
    await asyncio.wait_for(log.replay_cancelled.wait(), timeout=0.1)
    closing.cancel()
    log.release_cleanup.set()

    with pytest.raises(asyncio.CancelledError):
        await closing
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(waiting, timeout=0.1)
    assert broker.active_tenants() == ()
    assert broker._replay_tasks == {}
    assert broker._latest_tasks == {}


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
    await _wait_for_live_subscription(broker)
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


def test_encode_sse_frame_is_byte_compatible_with_uncached_encoding() -> None:
    event = _event(7, event_type="topic3.gate-c.probe", value="line-1\nline-2")
    expected = (
        f"id: signed-cursor\nevent: {event.event_type}\ndata: {event.data_json}\n\n"
    ).encode()

    assert encode_sse_frame(event, "signed-cursor") == expected
    assert event.frame_body == expected.removeprefix(b"id: signed-cursor\n")


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
    with pytest.raises(ValueError, match="replay_cache_seconds"):
        SSEBroker(InMemorySSEReplayLog(), replay_cache_seconds=0)

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

    with pytest.raises(ValueError, match="prefixes"):
        broker.subscribe("tenant-a", event_type_prefixes=("",))


@pytest.mark.asyncio
async def test_sse_delivery_observes_published_to_client_latency() -> None:
    metrics = PlatformMetrics()
    broker = SSEBroker(InMemorySSEReplayLog(), metrics=metrics)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=1)
    waiting = asyncio.create_task(anext(stream))
    await _wait_for_live_subscription(broker)
    event = await broker.publish("tenant-a", "topic4.test", {"value": 1})

    assert await waiting == event
    assert b'stage="published_to_client"' in metrics.render()
    await stream.aclose()


def test_sse_event_reuses_serialized_payload_for_fanout_and_frame_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original_dumps = sse_module.json.dumps

    def counted_dumps(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_dumps(*args, **kwargs)

    monkeypatch.setattr(sse_module.json, "dumps", counted_dumps)
    event = _event(7, value={"nested": ["value"]})

    assert event.size_bytes > 0
    for _ in range(128):
        assert sse_module.SSEBroker._event_size(event) == event.size_bytes
        assert b'"nested":["value"]' in sse_module.encode_sse_frame(event, "cursor")

    assert calls == 1


def test_replay_cursor_cache_is_bounded_lru_and_tenant_bound() -> None:
    codec = ReplayCursorCodec(b"x" * 32, cache_size=2)
    tenant_a_zero = codec.encode("tenant-a", 0)
    codec.encode("tenant-a", 1)
    assert codec.encode("tenant-a", 0) == tenant_a_zero

    codec.encode("tenant-a", 2)
    assert ("tenant-a", 1) not in codec._encoded
    assert codec.decode(tenant_a_zero, "tenant-a") == 0
    with pytest.raises(LiyanError):
        codec.decode(tenant_a_zero, "tenant-b")


@pytest.mark.asyncio
async def test_http_scope_uses_starlette_disconnect_owner_for_asgi_23() -> None:
    class Request:
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}}

        async def is_disconnected(self) -> bool:
            raise AssertionError("the response listener owns the ASGI 2.3 receive channel")

    broker = SSEBroker(InMemorySSEReplayLog())
    subscription = broker.subscribe("tenant-a", heartbeat_seconds=0.001)
    context = TenantContext(
        tenant_id="tenant-a",
        subject_ref="subject-a",
        roles=frozenset({"learner"}),
        scopes=frozenset({"topic4:sse:read"}),
        trace_id="0" * 32,
    )
    stream = TenantScopedSSEStream(Request(), subscription, context, object())

    assert await anext(stream) == b": heartbeat\n\n"
    assert stream._disconnect_task is None
    await stream.aclose()


@pytest.mark.asyncio
async def test_http_scope_falls_back_to_watcher_for_asgi_24() -> None:
    class Request:
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}}

        async def is_disconnected(self) -> bool:
            return False

    broker = SSEBroker(InMemorySSEReplayLog())
    subscription = broker.subscribe("tenant-a", heartbeat_seconds=0.001)
    context = TenantContext(
        tenant_id="tenant-a",
        subject_ref="subject-a",
        roles=frozenset({"learner"}),
        scopes=frozenset({"topic4:sse:read"}),
        trace_id="0" * 32,
    )
    stream = TenantScopedSSEStream(Request(), subscription, context, object())
    assert await anext(stream) == b": heartbeat\n\n"
    assert stream._disconnect_task is not None

    await stream.aclose()
    assert stream._disconnect_task is None


@pytest.mark.asyncio
async def test_owned_streaming_response_cancels_and_awaits_asgi_23_peer_task() -> None:
    body_closed = asyncio.Event()
    receive_cancelled = asyncio.Event()
    started = asyncio.Event()
    sent: list[dict[str, object]] = []

    async def body():
        try:
            yield b"data: ready\\n\\n"
            started.set()
            await asyncio.Event().wait()
        finally:
            body_closed.set()

    async def receive() -> dict[str, str]:
        try:
            await started.wait()
            return {"type": "http.disconnect"}
        except asyncio.CancelledError:
            receive_cancelled.set()
            raise

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    response = OwnedStreamingResponse(body(), media_type="text/event-stream")
    await response(
        {"type": "http", "asgi": {"spec_version": "2.3"}},
        receive,
        send,
    )

    assert body_closed.is_set()
    assert receive_cancelled.is_set() is False
    assert [message["type"] for message in sent] == [
        "http.response.start",
        "http.response.body",
    ]
    assert not any(
        task.get_name() in {"sse-response-send", "sse-response-disconnect"}
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
    )


@pytest.mark.asyncio
async def test_owned_streaming_response_closes_subscription_after_blocked_send_disconnect() -> None:
    broker = SSEBroker(InMemorySSEReplayLog(), subscriber_queue_size=4)
    context = TenantContext(
        tenant_id="tenant-a",
        subject_ref="subject-a",
        roles=frozenset({"learner"}),
        scopes=frozenset({"topic3:sse:read"}),
        trace_id="a" * 32,
    )
    subscription = broker.subscribe(context.tenant_id, heartbeat_seconds=60)
    stream = TenantScopedSSEStream(
        SimpleNamespace(scope={"type": "http", "asgi": {"spec_version": "2.3"}}),
        subscription,
        context,
        ReplayCursorCodec(b"s" * 32),
    )
    send_started = asyncio.Event()
    response = OwnedStreamingResponse(stream, media_type="text/event-stream")

    async def receive() -> dict[str, str]:
        await send_started.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            send_started.set()
            await asyncio.Event().wait()

    response_task = asyncio.create_task(
        response(
            {"type": "http", "asgi": {"spec_version": "2.3"}},
            receive,
            send,
        )
    )
    await _wait_for_live_subscription(broker)
    with tenant_scope(context):
        await broker.publish(context.tenant_id, "progress", {"value": 1})

    await asyncio.wait_for(response_task, timeout=1)

    assert stream._closed is True
    assert subscription._cleanup_complete is True
    assert broker.active_tenants() == ()
    assert not any(
        task.get_name().startswith("sse-response-")
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
    )


@pytest.mark.asyncio
async def test_owned_streaming_response_propagates_send_failure_after_peer_cleanup() -> None:
    receive_cancelled = asyncio.Event()

    async def body():
        yield b"data: ready\\n\\n"

    async def receive() -> dict[str, str]:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            receive_cancelled.set()
            raise
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.body":
            raise RuntimeError("socket write failed")

    response = OwnedStreamingResponse(body(), media_type="text/event-stream")
    with pytest.raises(RuntimeError, match="socket write failed"):
        await response(
            {"type": "http", "asgi": {"spec_version": "2.3"}},
            receive,
            send,
        )

    assert receive_cancelled.is_set()


@pytest.mark.asyncio
async def test_broker_reports_active_tenants_and_backpressure_drop() -> None:
    broker = SSEBroker(InMemorySSEReplayLog(), subscriber_queue_size=1)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=1)
    waiting = asyncio.create_task(anext(stream))
    await _wait_for_live_subscription(broker)
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
    await _wait_for_live_subscription(broker)
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
    await _wait_for_live_subscription(broker)

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


@pytest.mark.asyncio
async def test_subscription_context_manager_closes_and_rejects_further_iteration() -> None:
    broker = SSEBroker(InMemorySSEReplayLog())
    stream = broker.subscribe("tenant-a", heartbeat_seconds=0.001)

    async with stream as managed:
        assert managed is stream
        assert await anext(managed) is None
        assert broker.active_tenants() == ("tenant-a",)

    assert broker.active_tenants() == ()
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_subscription_close_failure_restores_retryable_state(monkeypatch) -> None:
    broker = SSEBroker(InMemorySSEReplayLog())
    stream = broker.subscribe("tenant-a", heartbeat_seconds=0.001)
    assert await anext(stream) is None

    async def fail_remove(_tenant_id, _subscriber) -> None:
        raise RuntimeError("injected close failure")

    monkeypatch.setattr(broker, "_remove_subscriber_cancellation_safe", fail_remove)

    with pytest.raises(RuntimeError, match="close failure"):
        await stream.aclose()

    assert stream._closing is False
    assert stream._cleanup_complete is False
    monkeypatch.undo()
    await stream.aclose()


@pytest.mark.asyncio
async def test_subscription_replay_fails_closed_when_durable_target_is_missing() -> None:
    class MissingTargetReplayLog(InMemorySSEReplayLog):
        async def replay(self, tenant_id, after_sequence):
            del tenant_id, after_sequence
            return []

        async def latest_sequence(self, tenant_id):
            assert tenant_id == "tenant-a"
            return 3

    broker = SSEBroker(MissingTargetReplayLog())
    stream = broker.subscribe("tenant-a", after_sequence=0)

    with pytest.raises(LiyanError) as error:
        await anext(stream)

    assert error.value.code == ErrorCode.MESSAGE_SEQUENCE_GAP
    assert broker.active_tenants() == ()


@pytest.mark.asyncio
async def test_replay_buffer_conflict_and_bounds_close_subscriber() -> None:
    class BlockingReplayLog(InMemorySSEReplayLog):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def replay(self, tenant_id, after_sequence):
            del tenant_id, after_sequence
            self.started.set()
            await self.release.wait()
            return []

    conflict_log = BlockingReplayLog()
    conflict_broker = SSEBroker(conflict_log)
    conflict_stream = conflict_broker.subscribe("tenant-a")
    conflict_wait = asyncio.create_task(anext(conflict_stream))
    await conflict_log.started.wait()
    conflict_subscriber = next(iter(conflict_broker._subscribers["tenant-a"]))

    first = _event(0, value="first")
    conflicting = _event(0, value="conflicting")
    async with conflict_broker._tenant_locks["tenant-a"]:
        conflict_broker._buffer_replay_event_locked(
            "tenant-a",
            conflict_subscriber,
            first,
        )
        conflict_broker._buffer_replay_event_locked(
            "tenant-a",
            conflict_subscriber,
            conflicting,
        )
    assert conflict_subscriber.closed is True
    conflict_log.release.set()
    await asyncio.gather(conflict_wait, return_exceptions=True)
    await conflict_stream.aclose()

    bounded_log = BlockingReplayLog()
    bounded_broker = SSEBroker(
        bounded_log,
        replay_buffer_max_events=1,
        replay_buffer_max_bytes=1024,
    )
    bounded_stream = bounded_broker.subscribe("tenant-a")
    bounded_wait = asyncio.create_task(anext(bounded_stream))
    await bounded_log.started.wait()
    bounded_subscriber = next(iter(bounded_broker._subscribers["tenant-a"]))

    async with bounded_broker._tenant_locks["tenant-a"]:
        bounded_broker._buffer_replay_event_locked(
            "tenant-a",
            bounded_subscriber,
            _event(0),
        )
        bounded_broker._buffer_replay_event_locked(
            "tenant-a",
            bounded_subscriber,
            _event(1),
        )
    assert bounded_subscriber.closed is True
    bounded_log.release.set()
    await asyncio.gather(bounded_wait, return_exceptions=True)
    await bounded_stream.aclose()


@pytest.mark.asyncio
async def test_replay_cache_enforces_size_tenant_and_expiry_bounds() -> None:
    oversized = SSEBroker(
        InMemorySSEReplayLog(),
        replay_cache_max_events=1,
        replay_cache_max_bytes=1024,
    )
    oversized._store_replay_cache("tenant-a", None, (_event(0), _event(1)))
    assert oversized._replay_cache == {}

    broker = SSEBroker(
        InMemorySSEReplayLog(),
        replay_cache_seconds=0.001,
        replay_cache_max_events=8,
        replay_cache_max_bytes=45,
        replay_cache_max_tenants=1,
    )
    broker._store_replay_cache("tenant-a", None, (_event(0, value="a"),))
    broker._store_replay_cache("tenant-a", None, (_event(1, value="b"),))
    assert broker._replay_cache_events == 1
    assert broker._replay_cache_bytes > 0

    broker._store_replay_cache("tenant-b", None, (_event(0, tenant_id="tenant-b"),))
    assert tuple(broker._replay_cache) == ("tenant-b",)

    for sequence in range(4):
        broker._store_replay_cache(
            "tenant-b",
            sequence,
            (_event(sequence + 1, tenant_id="tenant-b", value="x" * 10),),
        )
    assert broker._replay_cache_bytes <= broker._replay_cache_max_bytes

    event_bounded = SSEBroker(
        InMemorySSEReplayLog(),
        replay_cache_max_events=3,
        replay_cache_max_bytes=4096,
    )
    event_bounded._store_replay_cache("tenant-a", None, (_event(0), _event(1)))
    event_bounded._store_replay_cache("tenant-a", 2, (_event(3), _event(4)))
    assert event_bounded._replay_cache_events == 2
    assert tuple(event_bounded._replay_cache["tenant-a"]) == (2,)

    tenant_cache = broker._replay_cache["tenant-b"]
    for cursor, entry in list(tenant_cache.items()):
        tenant_cache[cursor] = replace(entry, expires_at=0)
    assert broker._cached_replay("tenant-b", None, None) is None
    assert "tenant-b" not in broker._replay_cache
    assert broker._replay_cache_events == 0
    assert broker._replay_cache_bytes == 0


@pytest.mark.asyncio
async def test_replay_cache_expires_without_a_followup_cache_access() -> None:
    metrics = PlatformMetrics()
    broker = SSEBroker(
        InMemorySSEReplayLog(),
        replay_cache_seconds=0.005,
        metrics=metrics,
    )
    broker._store_replay_cache("tenant-a", None, (_event(0),))
    assert broker._replay_cache_events == 1

    await asyncio.sleep(0.02)

    assert broker._replay_cache == {}
    assert broker._replay_cache_events == 0
    assert broker._replay_cache_bytes == 0
    rendered = metrics.render()
    assert b'metric="replay_cache_events"} 0.0' in rendered
    assert b'metric="replay_cache_bytes"} 0.0' in rendered


@pytest.mark.asyncio
async def test_sse_hot_path_throttles_gauge_writes_and_forces_cleanup_state() -> None:
    class CountingMetrics:
        def __init__(self) -> None:
            self.gauges: dict[str, int] = {}
            self.calls: dict[str, int] = {}

        def observe_sse(self, *_args, **_kwargs) -> None:
            return None

        def observe_sse_latency(self, *_args, **_kwargs) -> None:
            return None

        def set_sse_gauge(self, metric: str, value: int) -> None:
            self.gauges[metric] = value
            self.calls[metric] = self.calls.get(metric, 0) + 1

    metrics = CountingMetrics()
    log = InMemorySSEReplayLog(capacity_per_tenant=256)
    broker = SSEBroker(log, subscriber_queue_size=128, metrics=metrics)
    stream = broker.subscribe("tenant-a", heartbeat_seconds=0.001)
    assert await anext(stream) is None

    for ordinal in range(100):
        event = await log.append("tenant-a", "topic4.probe", {"ordinal": ordinal})
        assert await broker.deliver(event) == 1

    assert broker._queued_events == 100
    assert metrics.calls["queued_events"] < 10

    await stream.aclose()

    assert metrics.gauges["subscribers"] == 0
    assert metrics.gauges["queued_events"] == 0
    assert metrics.gauges["queued_bytes"] == 0


@pytest.mark.asyncio
async def test_latest_cache_is_monotonic_bounded_and_expires() -> None:
    broker = SSEBroker(
        InMemorySSEReplayLog(),
        replay_cache_seconds=0.001,
        replay_cache_max_tenants=1,
    )

    assert broker._store_latest_sequence("tenant-a", 5) == 5
    assert broker._store_latest_sequence("tenant-a", 3) == 5
    assert broker._store_latest_sequence("tenant-b", 1) == 1
    assert tuple(broker._latest_cache) == ("tenant-b",)

    broker._latest_cache["tenant-b"] = replace(
        broker._latest_cache["tenant-b"],
        expires_at=0,
    )
    assert broker._cached_latest_sequence("tenant-b") == (False, None)


def test_chunk_assembler_fails_closed_on_identity_and_sequence_conflicts() -> None:
    stream_id = uuid4()
    candidate_id = uuid4()
    chunks = make_text_chunks(
        "abcdefghijkl",
        stream_id=stream_id,
        candidate_id=candidate_id,
        candidate_version=1,
        block_id="block-conflict",
        max_bytes=4,
    )

    fragment_conflict = SSEChunkAssembler()
    fragment_conflict.add(chunks[0])
    with pytest.raises(LiyanError) as reused_fragment:
        fragment_conflict.add(
            chunks[0].model_copy(
                update={
                    "data": "zzzz",
                    "data_sha256": "f" * 64,
                }
            )
        )
    assert reused_fragment.value.code == ErrorCode.SSE_FRAGMENT_CONFLICT
    assert fragment_conflict.add(chunks[0]) is False

    duplicate_index = SSEChunkAssembler()
    duplicate_index.add(chunks[0])
    assert duplicate_index.add(chunks[0].model_copy(update={"fragment_id": uuid4()})) is False

    older_index = SSEChunkAssembler()
    older_index.add(chunks[0])
    state = next(iter(older_index._states.values()))
    state.index_digests.pop(0)
    state.fragment_digests.clear()
    with pytest.raises(LiyanError) as stale:
        older_index.add(chunks[0].model_copy(update={"fragment_id": uuid4()}))
    assert stale.value.code == ErrorCode.SSE_FRAGMENT_CONFLICT

    beyond_final = SSEChunkAssembler()
    beyond_final.add(chunks[2])
    with pytest.raises(LiyanError) as trailing:
        beyond_final.add(chunks[0].model_copy(update={"is_final": True}))
    assert trailing.value.code == ErrorCode.SSE_FRAGMENT_CONFLICT

    invalid_first = SSEChunkAssembler()
    with pytest.raises(LiyanError) as first_type:
        invalid_first.add(
            chunks[1].model_copy(
                update={
                    "chunk_index": 0,
                    "fragment_id": uuid4(),
                }
            )
        )
    assert first_type.value.code == ErrorCode.SSE_FRAGMENT_CONFLICT

    repeated_start = SSEChunkAssembler()
    repeated_start.add(chunks[0])
    with pytest.raises(LiyanError) as start_after_zero:
        repeated_start.add(
            chunks[0].model_copy(
                update={
                    "chunk_index": 1,
                    "fragment_id": uuid4(),
                }
            )
        )
    assert start_after_zero.value.code == ErrorCode.SSE_FRAGMENT_CONFLICT


def test_cursor_codec_rejects_structure_signature_and_negative_sequence() -> None:
    secret = b"x" * 32
    codec = ReplayCursorCodec(secret)

    malformed = base64.urlsafe_b64encode(b"tenant-a:1.invalid").decode().rstrip("=")
    with pytest.raises(LiyanError):
        codec.decode(malformed, "tenant-a")

    payload = b"tenant-a:1"
    invalid_signature = base64.urlsafe_b64encode(payload + b"." + b"0" * 32).decode().rstrip("=")
    with pytest.raises(LiyanError):
        codec.decode(invalid_signature, "tenant-a")

    negative_payload = b"tenant-a:-1"
    signature = hmac.new(secret, negative_payload, hashlib.sha256).digest()
    negative = base64.urlsafe_b64encode(negative_payload + b"." + signature).decode().rstrip("=")
    with pytest.raises(LiyanError):
        codec.decode(negative, "tenant-a")


@pytest.mark.asyncio
async def test_closed_marker_and_closing_state_stop_subscription_immediately() -> None:
    broker = SSEBroker(InMemorySSEReplayLog())
    stream = broker.subscribe("tenant-a", heartbeat_seconds=60)
    waiting = asyncio.create_task(anext(stream))
    await _wait_for_live_subscription(broker)
    subscriber = next(iter(broker._subscribers["tenant-a"]))

    async with broker._tenant_locks["tenant-a"]:
        broker._close_subscriber_locked("tenant-a", subscriber)

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(waiting, timeout=0.1)
    assert broker.active_tenants() == ()

    closing = broker.subscribe("tenant-a")
    closing._closing = True
    with pytest.raises(StopAsyncIteration):
        await closing._ensure_initialized()


@pytest.mark.asyncio
async def test_subscription_handoff_closes_on_retention_gap() -> None:
    class RetentionGapReplayLog(InMemorySSEReplayLog):
        def __init__(self) -> None:
            super().__init__()
            self.first_replay_started = asyncio.Event()
            self.release_first_replay = asyncio.Event()
            self.replay_calls = 0

        async def latest_sequence(self, tenant_id):
            assert tenant_id == "tenant-a"
            return 1

        async def replay(self, tenant_id, after_sequence):
            assert tenant_id == "tenant-a"
            self.replay_calls += 1
            if self.replay_calls == 1:
                self.first_replay_started.set()
                await self.release_first_replay.wait()
                return [_event(1)]
            raise LiyanError(
                ErrorCode.SSE_REPLAY_CURSOR_INVALID,
                "retention gap",
                category=ErrorCategory.MESSAGING,
            )

    log = RetentionGapReplayLog()
    broker = SSEBroker(log)
    stream = broker.subscribe("tenant-a", after_sequence=0)
    waiting = asyncio.create_task(anext(stream))
    await log.first_replay_started.wait()

    assert await broker.deliver(_event(3)) == 0
    log.release_first_replay.set()

    with pytest.raises(StopAsyncIteration):
        await waiting
    assert broker.active_tenants() == ()


@pytest.mark.asyncio
async def test_no_cursor_handoff_uses_durable_watermark_for_buffered_live_event() -> None:
    class EmptyDelayedReplayLog(InMemorySSEReplayLog):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def latest_sequence(self, tenant_id):
            assert tenant_id == "tenant-a"
            return 1

        async def replay(self, tenant_id, after_sequence):
            del tenant_id, after_sequence
            self.started.set()
            await self.release.wait()
            return []

    log = EmptyDelayedReplayLog()
    broker = SSEBroker(log)
    stream = broker.subscribe("tenant-a")
    waiting = asyncio.create_task(anext(stream))
    await log.started.wait()

    live = _event(2)
    assert await broker.deliver(live) == 0
    log.release.set()

    assert await waiting == live
    await stream.aclose()


@pytest.mark.asyncio
async def test_internal_fanout_and_cache_miss_paths_fail_closed() -> None:
    broker = SSEBroker(InMemorySSEReplayLog(), subscriber_queue_size=2)
    closed_stream = broker.subscribe("tenant-a", heartbeat_seconds=0.001)
    assert await anext(closed_stream) is None
    closed = closed_stream._subscriber
    assert closed is not None
    await closed_stream.aclose()

    replaying_stream = broker.subscribe("tenant-a")
    replaying = replaying_stream._subscriber
    assert replaying is None
    await broker._initialize_subscription(replaying_stream)
    replaying = replaying_stream._subscriber
    assert replaying is not None
    replaying.state = "REPLAYING"

    gap_stream = broker.subscribe("tenant-a", after_sequence=0)
    await broker._initialize_subscription(gap_stream)
    gap = gap_stream._subscriber
    assert gap is not None
    gap.state = "LIVE"
    gap.last_sequence = 0

    broker._subscribers["tenant-a"].add(closed)
    event = _event(2)
    delivered = broker._fan_out_locked("tenant-a", [event])

    assert delivered == 0
    assert replaying.replay_buffer[2] == event
    assert gap.closed is True
    assert closed not in broker._subscribers["tenant-a"]
    broker._buffer_replay_event_locked("tenant-a", replaying, _event(1, tenant_id="tenant-b"))

    broker._store_replay_cache("tenant-a", 0, (_event(1),))
    assert broker._cached_replay("tenant-a", 99, None) is None
    assert broker._cached_replay("tenant-a", 0, 2) is None

    byte_bounded = SSEBroker(
        InMemorySSEReplayLog(),
        replay_cache_max_tenants=2,
        replay_cache_max_bytes=30,
    )
    byte_bounded._store_replay_cache("tenant-a", None, (_event(0, value="a"),))
    byte_bounded._store_replay_cache(
        "tenant-b",
        None,
        (_event(0, tenant_id="tenant-b", value="b"),),
    )
    assert tuple(byte_bounded._replay_cache) == ("tenant-b",)

    await replaying_stream.aclose()
    await gap_stream.aclose()


@pytest.mark.asyncio
async def test_subscription_marker_and_post_receive_close_paths_release_cleanly(
    monkeypatch,
) -> None:
    broker = SSEBroker(InMemorySSEReplayLog())
    marked = broker.subscribe("tenant-a", heartbeat_seconds=0.001)
    assert await anext(marked) is None
    marked_subscriber = marked._subscriber
    assert marked_subscriber is not None
    marked_subscriber.queue.put_nowait(sse_module._SUBSCRIBER_CLOSED)

    with pytest.raises(StopAsyncIteration):
        await anext(marked)

    closing = broker.subscribe("tenant-a", heartbeat_seconds=0.001)
    assert await anext(closing) is None
    closing_subscriber = closing._subscriber
    assert closing_subscriber is not None
    closing_subscriber.queue.put_nowait(_event(0))

    async def already_initialized() -> None:
        return None

    monkeypatch.setattr(closing, "_ensure_initialized", already_initialized)
    closing._closing = True
    with pytest.raises(StopAsyncIteration):
        await anext(closing)
    closing._closing = False
    await closing.aclose()


@pytest.mark.asyncio
async def test_broker_background_detach_sync_and_error_paths_are_bounded() -> None:
    class FailingReplayLog(InMemorySSEReplayLog):
        def __init__(self) -> None:
            super().__init__()
            self.fail = False

        async def replay(self, tenant_id, after_sequence):
            if self.fail:
                raise LiyanError(
                    ErrorCode.INTERNAL,
                    "injected replay failure",
                    category=ErrorCategory.MESSAGING,
                )
            return await super().replay(tenant_id, after_sequence)

    log = FailingReplayLog()
    broker = SSEBroker(log)
    uninitialized = broker.subscribe("tenant-a")
    await broker._activate_subscription(uninitialized, [])
    assert await broker.synchronize("tenant-a") == 0

    latest = asyncio.create_task(asyncio.Event().wait())
    replay = asyncio.create_task(asyncio.Event().wait())
    other_tenant = asyncio.create_task(asyncio.Event().wait())
    broker._latest_tasks["tenant-a"] = latest
    broker._replay_tasks[("tenant-a", None, None)] = replay
    broker._replay_tasks[("tenant-b", None, None)] = other_tenant

    detached = broker._detach_tenant_background_tasks("tenant-a")
    assert set(detached) == {latest, replay}
    assert broker._replay_tasks == {("tenant-b", None, None): other_tenant}
    for task in [*detached, other_tenant]:
        task.cancel()
    await asyncio.gather(*detached, other_tenant, return_exceptions=True)

    stream = broker.subscribe("tenant-a", heartbeat_seconds=0.001)
    assert await anext(stream) is None
    log.fail = True
    with pytest.raises(LiyanError) as replay_error:
        await broker.synchronize("tenant-a")
    assert replay_error.value.code == ErrorCode.INTERNAL
    await stream.aclose()

    with pytest.raises(ValueError, match="another tenant"):
        broker._fan_out_locked("tenant-a", [_event(0, tenant_id="tenant-b")])

    class ObserveOnlyMetrics:
        def observe_sse(self, _operation, _outcome, _count=1) -> None:
            return None

    metrics_broker = SSEBroker(InMemorySSEReplayLog(), metrics=ObserveOnlyMetrics())
    metrics_broker._update_sse_gauges()


@pytest.mark.asyncio
async def test_streaming_validates_cursor_events_replay_and_cache_configuration() -> None:
    with pytest.raises(ValueError, match="gap_buffer"):
        SSEChunkAssembler(max_gap_buffer=0)
    with pytest.raises(ValueError, match="cache bounds"):
        SSEBroker(InMemorySSEReplayLog(), replay_cache_max_events=0)
    with pytest.raises(ValueError, match="buffer bounds"):
        SSEBroker(InMemorySSEReplayLog(), replay_buffer_max_events=0)

    with pytest.raises(ValueError, match="at least 32"):
        ReplayCursorCodec(b"short")

    valid_codec = ReplayCursorCodec(b"x" * 32)
    with pytest.raises(ValueError, match="nonnegative"):
        valid_codec.encode("tenant-a", -1)
    with pytest.raises(LiyanError) as malformed:
        valid_codec.decode("not-base64!", "tenant-a")
    assert malformed.value.code == ErrorCode.SSE_REPLAY_CURSOR_INVALID

    broker = SSEBroker(InMemorySSEReplayLog())
    with pytest.raises(ValueError, match="nonnegative"):
        await broker.deliver(_event(-1))
    with pytest.raises(ValueError, match="another tenant"):
        broker._merge_replay_events("tenant-a", [_event(0, tenant_id="tenant-b")])
    with pytest.raises(ValueError, match="conflicting"):
        broker._merge_replay_events(
            "tenant-a",
            [_event(0, value="first")],
            [_event(0, value="second")],
        )
    assert broker._first_sequence_gap([_event(0), _event(2)], after_sequence=None) == 0
    with pytest.raises(ValueError, match="noncontiguous"):
        broker._validate_replay("tenant-a", [_event(2)], after_sequence=0)
