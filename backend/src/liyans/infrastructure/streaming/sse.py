from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import re
from collections import OrderedDict, defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Protocol
from uuid import UUID, uuid4

from liyans_contracts.topic3 import SSEChunkV1, StreamFragmentType

from liyans.core.async_cleanup import complete_cleanup
from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError, MessageConflictError
from liyans.core.hashing import sha256_hex

SSE_EVENT_TYPE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def validate_sse_event(
    event_type: str,
    data: dict[str, Any],
    *,
    max_event_bytes: int,
) -> None:
    if not SSE_EVENT_TYPE_PATTERN.fullmatch(event_type):
        raise LiyanError(
            ErrorCode.SSE_EVENT_INVALID,
            "The SSE event type is invalid.",
            category=ErrorCategory.CONTRACT,
            status_code=422,
        )
    try:
        encoded = json.dumps(
            data,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise LiyanError(
            ErrorCode.SSE_EVENT_INVALID,
            "The SSE event data is not a finite JSON object.",
            category=ErrorCategory.CONTRACT,
            status_code=422,
        ) from exc
    if len(encoded) > max_event_bytes:
        raise LiyanError(
            ErrorCode.SSE_EVENT_INVALID,
            "The SSE event exceeds the configured size limit.",
            category=ErrorCategory.CONTRACT,
            status_code=413,
        )


def split_utf8_safely(text: str, max_bytes: int) -> list[str]:
    if max_bytes < 4:
        raise ValueError("max_bytes must be at least four")
    if not text:
        return [""]
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for character in text:
        encoded_size = len(character.encode("utf-8"))
        if current and current_size + encoded_size > max_bytes:
            chunks.append("".join(current))
            current = []
            current_size = 0
        current.append(character)
        current_size += encoded_size
    if current:
        chunks.append("".join(current))
    return chunks


def make_text_chunks(
    text: str,
    *,
    stream_id: UUID,
    candidate_id: UUID,
    candidate_version: int,
    block_id: str | None,
    max_bytes: int = 16_384,
) -> list[SSEChunkV1]:
    fragments = split_utf8_safely(text, max_bytes)
    chunks: list[SSEChunkV1] = []
    for index, data in enumerate(fragments):
        if len(fragments) == 1:
            fragment_type = StreamFragmentType.SNAPSHOT
            is_final = True
        elif index == 0:
            fragment_type = StreamFragmentType.START
            is_final = False
        elif index == len(fragments) - 1:
            fragment_type = StreamFragmentType.END
            is_final = True
        else:
            fragment_type = StreamFragmentType.DELTA
            is_final = False
        chunks.append(
            SSEChunkV1(
                schema_version="topic3.sse-chunk.v1",
                stream_id=stream_id,
                fragment_id=uuid4(),
                candidate_id=candidate_id,
                candidate_version=candidate_version,
                block_id=block_id,
                fragment_type=fragment_type,
                chunk_index=index,
                is_final=is_final,
                data_encoding="utf-8-text",
                data=data,
                data_sha256=sha256_hex(data.encode("utf-8")),
                emitted_at=datetime.now(UTC),
            )
        )
    return chunks


@dataclass(slots=True)
class _AssemblyState:
    expected_index: int = 0
    pending: dict[int, SSEChunkV1] = field(default_factory=dict)
    index_digests: dict[int, str] = field(default_factory=dict)
    fragment_digests: dict[UUID, str] = field(default_factory=dict)
    parts: list[str] = field(default_factory=list)
    closed: bool = False


class SSEChunkAssembler:
    def __init__(self, *, max_gap_buffer: int = 128) -> None:
        if max_gap_buffer < 1:
            raise ValueError("max_gap_buffer must be positive")
        self._max_gap_buffer = max_gap_buffer
        self._states: dict[tuple[UUID, UUID, int, str | None], _AssemblyState] = {}

    def add(self, chunk: SSEChunkV1) -> bool:
        key = (
            chunk.stream_id,
            chunk.candidate_id,
            chunk.candidate_version,
            chunk.block_id,
        )
        state = self._states.setdefault(key, _AssemblyState())
        existing_fragment = state.fragment_digests.get(chunk.fragment_id)
        if existing_fragment is not None:
            if existing_fragment != chunk.data_sha256:
                raise MessageConflictError(
                    ErrorCode.SSE_FRAGMENT_CONFLICT,
                    "The fragment identity was reused with different data.",
                )
            return False
        existing_index = state.index_digests.get(chunk.chunk_index)
        if existing_index is not None:
            if existing_index != chunk.data_sha256:
                raise MessageConflictError(
                    ErrorCode.SSE_FRAGMENT_CONFLICT,
                    "The stream index was reused with different data.",
                )
            state.fragment_digests[chunk.fragment_id] = chunk.data_sha256
            return False
        if state.closed:
            raise MessageConflictError(
                ErrorCode.SSE_STREAM_CLOSED,
                "The stream already received its final fragment.",
            )
        if chunk.chunk_index < state.expected_index:
            raise MessageConflictError(
                ErrorCode.SSE_FRAGMENT_CONFLICT,
                "The fragment index is older than the assembled cursor.",
            )
        if chunk.chunk_index > state.expected_index:
            if len(state.pending) >= self._max_gap_buffer:
                raise LiyanError(
                    ErrorCode.MESSAGE_BUFFER_FULL,
                    "The SSE fragment gap buffer is full.",
                    category=ErrorCategory.MESSAGING,
                    retriable=True,
                    status_code=503,
                )
            state.pending[chunk.chunk_index] = chunk
            state.index_digests[chunk.chunk_index] = chunk.data_sha256
            state.fragment_digests[chunk.fragment_id] = chunk.data_sha256
            return True

        self._accept(state, chunk)
        while state.expected_index in state.pending and not state.closed:
            next_chunk = state.pending.pop(state.expected_index)
            self._accept(state, next_chunk, identifiers_recorded=True)
        if state.closed and state.pending:
            raise MessageConflictError(
                ErrorCode.SSE_FRAGMENT_CONFLICT,
                "Fragments exist beyond the final stream fragment.",
            )
        return True

    def assembled_text(
        self,
        *,
        stream_id: UUID,
        candidate_id: UUID,
        candidate_version: int,
        block_id: str | None,
    ) -> str:
        key = (stream_id, candidate_id, candidate_version, block_id)
        state = self._states.get(key)
        if state is None or not state.closed:
            raise LiyanError(
                ErrorCode.MESSAGE_SEQUENCE_GAP,
                "The SSE stream is not complete.",
                category=ErrorCategory.MESSAGING,
                status_code=409,
            )
        return "".join(state.parts)

    @staticmethod
    def _accept(
        state: _AssemblyState,
        chunk: SSEChunkV1,
        *,
        identifiers_recorded: bool = False,
    ) -> None:
        if state.expected_index == 0 and chunk.fragment_type not in {
            StreamFragmentType.START,
            StreamFragmentType.SNAPSHOT,
        }:
            raise MessageConflictError(
                ErrorCode.SSE_FRAGMENT_CONFLICT,
                "The first fragment must be START or SNAPSHOT.",
            )
        if state.expected_index > 0 and chunk.fragment_type in {
            StreamFragmentType.START,
            StreamFragmentType.SNAPSHOT,
        }:
            raise MessageConflictError(
                ErrorCode.SSE_FRAGMENT_CONFLICT,
                "START and SNAPSHOT are only valid at stream index zero.",
            )
        if not identifiers_recorded:
            state.index_digests[chunk.chunk_index] = chunk.data_sha256
            state.fragment_digests[chunk.fragment_id] = chunk.data_sha256
        state.parts.append(chunk.data)
        state.expected_index += 1
        state.closed = chunk.is_final


@dataclass(frozen=True, slots=True)
class SSEEvent:
    tenant_id: str
    sequence: int
    event_type: str
    data: dict[str, Any]
    emitted_at: datetime
    _data_json: str = field(init=False, repr=False, compare=False)
    _frame_body: bytes = field(init=False, repr=False, compare=False)
    _size_bytes: int = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # One committed event is shared by every subscriber. Keep its stable
        # representation on the event so fan-out does not serialize per client.
        encoded = json.dumps(
            self.data,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        object.__setattr__(self, "_data_json", encoded)
        lines = [f"event: {self.event_type}"]
        lines.extend(f"data: {line}" for line in encoded.splitlines() or [""])
        object.__setattr__(self, "_frame_body", ("\n".join(lines) + "\n\n").encode("utf-8"))
        object.__setattr__(
            self,
            "_size_bytes",
            len(self.event_type.encode("utf-8")) + len(encoded.encode("utf-8")),
        )

    @property
    def data_json(self) -> str:
        return self._data_json

    @property
    def size_bytes(self) -> int:
        return self._size_bytes

    @property
    def frame_body(self) -> bytes:
        return self._frame_body


class SSEReplayLog(Protocol):
    async def append(
        self,
        tenant_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> SSEEvent: ...

    async def replay(
        self,
        tenant_id: str,
        after_sequence: int | None,
    ) -> list[SSEEvent]: ...

    async def latest_sequence(self, tenant_id: str) -> int | None: ...


class SSEMetricsObserver(Protocol):
    def observe_sse(self, operation: str, outcome: str, count: int = 1) -> None: ...

    def observe_sse_latency(self, stage: str, duration_seconds: float) -> None: ...

    def set_sse_gauge(self, metric: str, value: int) -> None: ...


class ReplayCursorCodec:
    def __init__(self, secret: bytes, *, cache_size: int = 8192) -> None:
        if len(secret) < 32:
            raise ValueError("SSE cursor secret must contain at least 32 bytes")
        if not 1 <= cache_size <= 100_000:
            raise ValueError("SSE cursor cache_size must be between one and 100000")
        self._secret = secret
        self._cache_size = cache_size
        self._encoded: OrderedDict[tuple[str, int], str] = OrderedDict()

    def encode(self, tenant_id: str, sequence: int) -> str:
        if not tenant_id or sequence < 0:
            raise ValueError("SSE cursor tenant and nonnegative sequence are required")
        key = (tenant_id, sequence)
        cached = self._encoded.get(key)
        if cached is not None:
            self._encoded.move_to_end(key)
            return cached
        payload = f"{tenant_id}:{sequence}".encode()
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        cursor = base64.urlsafe_b64encode(payload + b"." + signature).decode("ascii").rstrip("=")
        self._encoded[key] = cursor
        self._encoded.move_to_end(key)
        while len(self._encoded) > self._cache_size:
            self._encoded.popitem(last=False)
        return cursor

    def decode(self, cursor: str, tenant_id: str) -> int:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            raw = base64.urlsafe_b64decode(padded.encode("ascii"))
            if len(raw) < 34 or raw[-33:-32] != b".":
                raise ValueError
            payload = raw[:-33]
            signature = raw[-32:]
            expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            cursor_tenant, sequence = payload.decode("utf-8").rsplit(":", 1)
            if cursor_tenant != tenant_id:
                raise ValueError
            decoded_sequence = int(sequence)
            if decoded_sequence < 0:
                raise ValueError
            return decoded_sequence
        except (ValueError, UnicodeError, binascii.Error) as exc:
            raise LiyanError(
                ErrorCode.SSE_REPLAY_CURSOR_INVALID,
                "The SSE replay cursor is invalid.",
                category=ErrorCategory.MESSAGING,
                status_code=400,
            ) from exc

    def diagnostic_inventory(self) -> dict[str, int]:
        return {"entries": len(self._encoded), "capacity": self._cache_size}


class InMemorySSEReplayLog:
    def __init__(
        self,
        *,
        capacity_per_tenant: int = 4096,
        max_event_bytes: int = 256 * 1024,
    ) -> None:
        if capacity_per_tenant < 1:
            raise ValueError("capacity_per_tenant must be positive")
        if max_event_bytes < 1:
            raise ValueError("max_event_bytes must be positive")
        self._capacity = capacity_per_tenant
        self._max_event_bytes = max_event_bytes
        self._events: dict[str, deque[SSEEvent]] = {}
        self._next_sequence: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def append(self, tenant_id: str, event_type: str, data: dict[str, Any]) -> SSEEvent:
        validate_sse_event(event_type, data, max_event_bytes=self._max_event_bytes)
        async with self._lock:
            sequence = self._next_sequence[tenant_id]
            self._next_sequence[tenant_id] += 1
            event = SSEEvent(
                tenant_id=tenant_id,
                sequence=sequence,
                event_type=event_type,
                data=dict(data),
                emitted_at=datetime.now(UTC),
            )
            events = self._events.setdefault(tenant_id, deque(maxlen=self._capacity))
            events.append(event)
            return event

    async def replay(self, tenant_id: str, after_sequence: int | None) -> list[SSEEvent]:
        async with self._lock:
            events = list(self._events.get(tenant_id, ()))
        if after_sequence is None:
            return events
        if events and after_sequence < events[0].sequence - 1:
            raise LiyanError(
                ErrorCode.SSE_REPLAY_CURSOR_INVALID,
                "The SSE replay cursor is older than the retained event window.",
                category=ErrorCategory.MESSAGING,
                status_code=409,
            )
        return [event for event in events if event.sequence > after_sequence]

    async def latest_sequence(self, tenant_id: str) -> int | None:
        async with self._lock:
            next_sequence = self._next_sequence.get(tenant_id, 0)
        return next_sequence - 1 if next_sequence else None


class _SubscriberClosed:
    """Private queue marker used to wake a blocked SSE subscription."""


_SUBSCRIBER_CLOSED = _SubscriberClosed()


@dataclass(eq=False, slots=True)
class _Subscriber:
    queue: asyncio.Queue[SSEEvent | _SubscriberClosed]
    last_sequence: int
    event_type_prefixes: tuple[str, ...] = ()
    state: str = "REPLAYING"
    replay_buffer: OrderedDict[int, SSEEvent] = field(default_factory=OrderedDict)
    replay_buffer_bytes: int = 0
    closed: bool = False


@dataclass(frozen=True, slots=True)
class _ReplayCacheEntry:
    events: tuple[SSEEvent, ...]
    expires_at: float
    size_bytes: int


@dataclass(frozen=True, slots=True)
class _LatestCacheEntry:
    sequence: int | None
    expires_at: float


class SSESubscription(AsyncIterator[SSEEvent | None]):
    """Single-owner SSE subscription with cancellation-safe, idempotent cleanup."""

    def __init__(
        self,
        broker: SSEBroker,
        tenant_id: str,
        *,
        after_sequence: int | None,
        heartbeat_seconds: float,
        event_type_prefixes: tuple[str, ...],
    ) -> None:
        self._broker = broker
        self._tenant_id = tenant_id
        self._after_sequence = after_sequence
        self._heartbeat_seconds = heartbeat_seconds
        self._event_type_prefixes = event_type_prefixes
        self._subscriber: _Subscriber | None = None
        self._initial_events: deque[SSEEvent] = deque()
        self._initialization_task: asyncio.Task[None] | None = None
        self._pending_receive: asyncio.Task[SSEEvent | _SubscriberClosed] | None = None
        self._close_lock = asyncio.Lock()
        self._close_started = False
        self._close_done = asyncio.Event()
        self._closing = False
        self._cleanup_complete = False
        self._initial_last_sequence: int | None = None
        self._advance_task: asyncio.Task[object] | None = None
        self._advance_done = asyncio.Event()
        self._ready = asyncio.Event()

    async def __aenter__(self) -> SSESubscription:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    def __aiter__(self) -> SSESubscription:
        return self

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    async def wait_ready(self) -> None:
        await self._ready.wait()

    async def __anext__(self) -> SSEEvent | None:
        if self._cleanup_complete:
            raise StopAsyncIteration
        current = asyncio.current_task()
        if self._advance_task is not None and self._advance_task is not current:
            raise RuntimeError("SSE subscription cannot be advanced concurrently")
        self._advance_task = current
        self._advance_done.clear()
        try:
            await self._ensure_initialized()
            if self._initial_events:
                initial_event = self._initial_events.popleft()
                if not self._initial_events:
                    await self._broker._drain_subscription_tail(self)
                return initial_event
            subscriber = self._subscriber
            if subscriber is None or subscriber.closed:
                await self.aclose()
                raise StopAsyncIteration
            receive = asyncio.create_task(
                subscriber.queue.get(),
                name="sse-subscriber-receive",
            )
            self._pending_receive = receive
            try:
                queued_event = await asyncio.wait_for(
                    receive,
                    timeout=self._heartbeat_seconds,
                )
            except TimeoutError:
                if self._closing or self._cleanup_complete:
                    raise StopAsyncIteration from None
                return None
            finally:
                if self._pending_receive is receive:
                    self._pending_receive = None
            if queued_event is _SUBSCRIBER_CLOSED:
                await self.aclose()
                raise StopAsyncIteration
            self._broker._event_dequeued(queued_event)
            if self._closing or self._cleanup_complete:
                raise StopAsyncIteration
            return queued_event
        except asyncio.CancelledError:
            if self._closing or self._cleanup_complete:
                raise StopAsyncIteration from None
            await complete_cleanup(self._aclose(current))
            raise
        finally:
            if self._advance_task is current:
                self._advance_task = None
            self._advance_done.set()

    async def aclose(self) -> None:
        await self._aclose(asyncio.current_task())

    async def _aclose(self, owner_task: asyncio.Task[object] | None) -> None:
        async with self._close_lock:
            if self._cleanup_complete:
                return
            if self._close_started:
                if self._advance_task is owner_task:
                    return
                owner = False
            else:
                self._close_started = True
                self._close_done.clear()
                self._closing = True
                owner = True
        if not owner:
            await complete_cleanup(self._close_done.wait())
            return
        self._broker._subscription_close_started()
        try:
            await complete_cleanup(self._close(owner_task))
        finally:
            self._broker._subscription_close_finished()
            self._close_done.set()

    async def _close(self, current: asyncio.Task[object] | None) -> None:
        try:
            initialization = self._initialization_task
            receive = self._pending_receive
            pending = [
                task
                for task in (initialization, receive)
                if task is not None and task is not current and not task.done()
            ]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if self._advance_task is not None and self._advance_task is not current:
                await complete_cleanup(self._advance_done.wait())
            subscriber = self._subscriber
            if subscriber is not None:
                await self._broker._remove_subscriber_cancellation_safe(
                    self._tenant_id,
                    subscriber,
                )
        except BaseException:
            self._close_started = False
            self._closing = False
            raise
        else:
            self._initial_events.clear()
            self._subscriber = None
            self._initialization_task = None
            self._pending_receive = None
            self._cleanup_complete = True
            self._closing = False

    async def _ensure_initialized(self) -> None:
        if self._closing or self._cleanup_complete:
            raise StopAsyncIteration
        if self._subscriber is not None and self._subscriber.state in {"DRAINING", "LIVE"}:
            return
        task = self._initialization_task
        if task is None:
            task = asyncio.create_task(
                self._broker._initialize_subscription(self),
                name="sse-subscription-initialize",
            )
            self._initialization_task = task
        try:
            await task
        finally:
            if task.done() and self._initialization_task is task:
                self._initialization_task = None


class SSEBroker:
    def __init__(
        self,
        replay_log: SSEReplayLog,
        *,
        subscriber_queue_size: int = 128,
        replay_cache_seconds: float = 2.0,
        replay_cache_max_events: int = 4096,
        replay_cache_max_bytes: int = 16 * 1024 * 1024,
        replay_cache_max_tenants: int = 128,
        replay_buffer_max_events: int = 4096,
        replay_buffer_max_bytes: int = 16 * 1024 * 1024,
        metrics: SSEMetricsObserver | None = None,
    ) -> None:
        if subscriber_queue_size < 1:
            raise ValueError("subscriber_queue_size must be positive")
        if replay_cache_seconds <= 0:
            raise ValueError("replay_cache_seconds must be positive")
        if min(replay_cache_max_events, replay_cache_max_bytes, replay_cache_max_tenants) < 1:
            raise ValueError("SSE replay cache bounds must be positive")
        if min(replay_buffer_max_events, replay_buffer_max_bytes) < 1:
            raise ValueError("SSE replay buffer bounds must be positive")
        self._replay_log = replay_log
        self._subscriber_queue_size = subscriber_queue_size
        self._replay_cache_seconds = replay_cache_seconds
        self._replay_cache_max_events = replay_cache_max_events
        self._replay_cache_max_bytes = replay_cache_max_bytes
        self._replay_cache_max_tenants = replay_cache_max_tenants
        self._replay_buffer_max_events = replay_buffer_max_events
        self._replay_buffer_max_bytes = replay_buffer_max_bytes
        self._metrics = metrics
        self._subscribers: dict[str, set[_Subscriber]] = defaultdict(set)
        self._tenant_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._synchronize_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._replay_cache: OrderedDict[str, OrderedDict[int | None, _ReplayCacheEntry]] = (
            OrderedDict()
        )
        self._replay_cache_events = 0
        self._replay_cache_bytes = 0
        self._replay_cache_expiry_handle: asyncio.TimerHandle | None = None
        self._closing_subscriptions = 0
        self._replay_tasks: dict[
            tuple[str, int | None, int | None], asyncio.Task[tuple[SSEEvent, ...]]
        ] = {}
        self._latest_tasks: dict[str, asyncio.Task[int | None]] = {}
        self._latest_cache: OrderedDict[str, _LatestCacheEntry] = OrderedDict()
        self._queued_events = 0
        self._queued_bytes = 0
        self._replay_buffer_events = 0
        self._replay_buffer_bytes = 0
        self._gauge_update_interval_seconds = 0.1
        self._next_gauge_update_at = 0.0

    async def publish(self, tenant_id: str, event_type: str, data: dict[str, Any]) -> SSEEvent:
        event = await self.persist(tenant_id, event_type, data)
        await self.deliver(event)
        return event

    async def persist(self, tenant_id: str, event_type: str, data: dict[str, Any]) -> SSEEvent:
        """Append an SSE event durably without synchronously fanning it out."""

        event = await self._replay_log.append(tenant_id, event_type, data)
        self._record_durable_event(event)
        self._observe("publish", "persisted")
        return event

    async def deliver(self, event: SSEEvent) -> int:
        """Fan out a committed event, replaying any detected sequence gap first."""

        if event.sequence < 0 or event.emitted_at.tzinfo is None:
            raise ValueError("SSE events require a nonnegative sequence and aware timestamp")
        tenant_id = event.tenant_id
        self._record_durable_event(event)
        lock = self._tenant_locks[tenant_id]
        lock_started = asyncio.get_running_loop().time()
        await lock.acquire()
        self._observe_latency("fanout_lock_wait", lock_started)
        try:
            subscribers = self._active_subscribers(tenant_id)
            if not subscribers:
                return 0
            replaying = [
                subscriber
                for subscriber in subscribers
                if subscriber.state in {"REPLAYING", "DRAINING"}
            ]
            for subscriber in replaying:
                self._buffer_replay_event_locked(tenant_id, subscriber, event)
            live = [subscriber for subscriber in subscribers if subscriber.state == "LIVE"]
            if not live:
                self._update_sse_gauges()
                return 0
            minimum_cursor = min(subscriber.last_sequence for subscriber in live)
            if event.sequence <= minimum_cursor + 1:
                return self._fan_out_locked(tenant_id, [event], live)
        finally:
            lock.release()
        return await self._synchronize_tenant(
            tenant_id,
            through_sequence=event.sequence,
            outcome="gap_recovered",
        )

    async def synchronize(self, tenant_id: str, *, through_sequence: int | None = None) -> int:
        """Close notification loss/reconnect gaps from the durable replay log."""

        if through_sequence is not None and through_sequence < 0:
            raise ValueError("through_sequence cannot be negative")
        return await self._synchronize_tenant(
            tenant_id,
            through_sequence=through_sequence,
            outcome="notification_sync",
        )

    def active_tenants(self) -> tuple[str, ...]:
        return tuple(
            tenant_id
            for tenant_id, subscribers in self._subscribers.items()
            if any(not subscriber.closed for subscriber in subscribers)
        )

    def diagnostic_inventory(self) -> dict[str, int]:
        subscribers = [
            subscriber
            for items in self._subscribers.values()
            for subscriber in items
            if not subscriber.closed
        ]
        return {
            "subscribers": len(subscribers),
            "subscribers_live": sum(item.state == "LIVE" for item in subscribers),
            "subscribers_replaying": sum(item.state == "REPLAYING" for item in subscribers),
            "subscribers_draining": sum(item.state == "DRAINING" for item in subscribers),
            "closing_subscriptions": self._closing_subscriptions,
            "queued_events": self._queued_events,
            "queued_bytes": self._queued_bytes,
            "replay_buffer_events": self._replay_buffer_events,
            "replay_buffer_bytes": self._replay_buffer_bytes,
            "replay_cache_tenants": len(self._replay_cache),
            "replay_cache_events": self._replay_cache_events,
            "replay_cache_bytes": self._replay_cache_bytes,
            "replay_tasks": len(self._replay_tasks) + len(self._latest_tasks),
            "tenant_locks": len(self._tenant_locks),
            "synchronize_locks": len(self._synchronize_locks),
        }

    def subscribe(
        self,
        tenant_id: str,
        *,
        after_sequence: int | None = None,
        heartbeat_seconds: float = 15.0,
        event_type_prefixes: tuple[str, ...] | None = None,
    ) -> SSESubscription:
        prefixes = tuple(event_type_prefixes or ())
        if any(not prefix or len(prefix) > 128 for prefix in prefixes):
            raise ValueError("SSE event type prefixes must be nonempty and bounded")
        return SSESubscription(
            self,
            tenant_id,
            after_sequence=after_sequence,
            heartbeat_seconds=heartbeat_seconds,
            event_type_prefixes=prefixes,
        )

    async def _initialize_subscription(self, subscription: SSESubscription) -> None:
        tenant_id = subscription._tenant_id
        after_sequence = subscription._after_sequence
        heartbeat_seconds = subscription._heartbeat_seconds
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        if after_sequence is not None and after_sequence < 0:
            raise ValueError("after_sequence cannot be negative")
        subscriber = subscription._subscriber
        if subscriber is None:
            subscriber = _Subscriber(
                asyncio.Queue(maxsize=self._subscriber_queue_size),
                last_sequence=after_sequence if after_sequence is not None else -1,
                event_type_prefixes=subscription._event_type_prefixes,
            )
            subscription._subscriber = subscriber
            async with self._tenant_locks[tenant_id]:
                self._subscribers[tenant_id].add(subscriber)
                self._observe("subscribe", "opened")
                self._update_sse_gauges(force=True)
        admission_started = asyncio.get_running_loop().time()
        self._observe("admission", "started")
        try:
            stage_started = asyncio.get_running_loop().time()
            latest_sequence = await self._latest_sequence(tenant_id)
            self._observe_latency("admission_latest", stage_started)
            subscription._initial_last_sequence = (
                latest_sequence if after_sequence is None else after_sequence
            )
            stage_started = asyncio.get_running_loop().time()
            replay = await self._subscription_replay(
                tenant_id,
                after_sequence,
                through_sequence=latest_sequence,
            )
            self._observe_latency("admission_replay", stage_started)
            self._validate_replay(tenant_id, replay, after_sequence=after_sequence)
            stage_started = asyncio.get_running_loop().time()
            await self._activate_subscription(subscription, replay)
            subscription._ready.set()
            self._observe_latency("admission_handoff", stage_started)
            self._observe("replay", "subscriber_replay", len(subscription._initial_events))
            self._observe("admission", "accepted")
            self._observe_latency("admission_total", admission_started)
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                self._observe("admission", "cancelled")
            elif isinstance(exc, LiyanError):
                self._observe("admission", self._admission_failure_outcome(exc))
            else:
                self._observe("admission", "failed")
            await self._remove_subscriber_cancellation_safe(tenant_id, subscriber)
            raise

    def _active_subscribers(self, tenant_id: str) -> list[_Subscriber]:
        return [
            subscriber
            for subscriber in self._subscribers.get(tenant_id, ())
            if not subscriber.closed
        ]

    async def _subscription_replay(
        self,
        tenant_id: str,
        after_sequence: int | None,
        *,
        through_sequence: int | None,
    ) -> list[SSEEvent]:
        cursor = after_sequence
        replay: list[SSEEvent] = []
        for _page in range(1024):
            page = await self._coalesced_replay(
                tenant_id,
                cursor,
                through_sequence=through_sequence,
            )
            if page:
                self._validate_replay(tenant_id, page, after_sequence=cursor)
                replay.extend(
                    event for event in page if not replay or event.sequence > replay[-1].sequence
                )
                cursor = page[-1].sequence
            if through_sequence is None or (cursor is not None and cursor >= through_sequence):
                return replay
            if not page:
                if after_sequence is None:
                    return replay
                raise LiyanError(
                    ErrorCode.MESSAGE_SEQUENCE_GAP,
                    "The latest SSE event is not yet visible in durable replay storage.",
                    category=ErrorCategory.MESSAGING,
                    retriable=True,
                    status_code=503,
                )
        raise LiyanError(
            ErrorCode.MESSAGE_BUFFER_FULL,
            "The SSE subscription replay page budget was exhausted.",
            category=ErrorCategory.MESSAGING,
            retriable=True,
            status_code=503,
        )

    async def _coalesced_replay(
        self,
        tenant_id: str,
        after_sequence: int | None,
        *,
        through_sequence: int | None,
    ) -> list[SSEEvent]:
        cached = self._cached_replay(tenant_id, after_sequence, through_sequence)
        if cached is not None:
            self._observe("replay", "subscription_cache_hit")
            return cached
        key = (tenant_id, after_sequence, through_sequence)
        task = self._replay_tasks.get(key)
        if task is None:
            task = asyncio.create_task(
                self._run_replay_query(
                    tenant_id,
                    after_sequence,
                    through_sequence=through_sequence,
                ),
                name="sse-replay-query",
            )
            self._replay_tasks[key] = task
            self._update_sse_gauges()
        return list(await asyncio.shield(task))

    async def _run_replay_query(
        self,
        tenant_id: str,
        after_sequence: int | None,
        *,
        through_sequence: int | None,
    ) -> tuple[SSEEvent, ...]:
        key = (tenant_id, after_sequence, through_sequence)
        try:
            events = tuple(await self._replay_log.replay(tenant_id, after_sequence))
            self._store_replay_cache(tenant_id, after_sequence, events)
            return events
        finally:
            if self._replay_tasks.get(key) is asyncio.current_task():
                self._replay_tasks.pop(key, None)
            self._update_sse_gauges()

    async def _latest_sequence(self, tenant_id: str) -> int | None:
        cached, sequence = self._cached_latest_sequence(tenant_id)
        if cached:
            self._observe("replay", "latest_cache_hit")
            return sequence
        task = self._latest_tasks.get(tenant_id)
        if task is None:
            task = asyncio.create_task(
                self._run_latest_sequence(tenant_id),
                name="sse-latest-sequence",
            )
            self._latest_tasks[tenant_id] = task
            self._update_sse_gauges()
        return await asyncio.shield(task)

    async def _run_latest_sequence(self, tenant_id: str) -> int | None:
        try:
            sequence = await self._replay_log.latest_sequence(tenant_id)
            return self._store_latest_sequence(tenant_id, sequence)
        finally:
            if self._latest_tasks.get(tenant_id) is asyncio.current_task():
                self._latest_tasks.pop(tenant_id, None)
            self._update_sse_gauges()

    async def _activate_subscription(
        self,
        subscription: SSESubscription,
        replay: list[SSEEvent],
    ) -> None:
        tenant_id = subscription._tenant_id
        subscriber = subscription._subscriber
        if subscriber is None:
            return
        merged = list(replay)
        for _attempt in range(1024):
            async with self._tenant_locks[tenant_id]:
                if subscriber.closed:
                    return
                buffered = list(subscriber.replay_buffer.values())
                combined = self._merge_replay_events(tenant_id, merged, buffered)
                handoff_after = subscription._after_sequence
                if buffered and not merged and handoff_after is None:
                    handoff_after = (
                        subscription._initial_last_sequence
                        if subscription._initial_last_sequence is not None
                        else -1
                    )
                gap_after = self._first_sequence_gap(
                    combined,
                    after_sequence=handoff_after,
                )
                if gap_after is None:
                    subscription._initial_events.extend(
                        event for event in combined if self._matches_subscriber(subscriber, event)
                    )
                    subscriber.last_sequence = (
                        combined[-1].sequence
                        if combined
                        else subscription._initial_last_sequence
                        if subscription._initial_last_sequence is not None
                        else -1
                    )
                    self._clear_replay_buffer_locked(subscriber)
                    subscriber.state = "DRAINING" if subscription._initial_events else "LIVE"
                    self._update_sse_gauges(force=True)
                    return
                target = max(event.sequence for event in buffered)
            try:
                missing = await self._subscription_replay(
                    tenant_id,
                    gap_after,
                    through_sequence=target,
                )
            except LiyanError as exc:
                if exc.code != ErrorCode.SSE_REPLAY_CURSOR_INVALID:
                    raise
                async with self._tenant_locks[tenant_id]:
                    self._close_subscriber_locked(tenant_id, subscriber)
                self._observe("replay", "retention_gap_drop")
                return
            merged = self._merge_replay_events(tenant_id, merged, missing)
        raise LiyanError(
            ErrorCode.MESSAGE_BUFFER_FULL,
            "The SSE replay/live handoff could not reach a contiguous sequence.",
            category=ErrorCategory.MESSAGING,
            retriable=True,
            status_code=503,
        )

    async def _drain_subscription_tail(self, subscription: SSESubscription) -> None:
        tenant_id = subscription._tenant_id
        subscriber = subscription._subscriber
        if subscriber is None:
            return
        merged: list[SSEEvent] = []
        for _attempt in range(1024):
            async with self._tenant_locks[tenant_id]:
                if subscriber.closed or subscriber.state != "DRAINING":
                    return
                buffered = list(subscriber.replay_buffer.values())
                combined = self._merge_replay_events(tenant_id, merged, buffered)
                gap_after = self._first_sequence_gap(
                    combined,
                    after_sequence=subscriber.last_sequence,
                )
                if gap_after is None:
                    matched = [
                        event for event in combined if self._matches_subscriber(subscriber, event)
                    ]
                    if combined:
                        subscriber.last_sequence = combined[-1].sequence
                    self._clear_replay_buffer_locked(subscriber)
                    if matched:
                        subscription._initial_events.extend(matched)
                        self._observe("replay", "terminal_tail_buffered", len(matched))
                        self._update_sse_gauges()
                        return
                    subscriber.state = "LIVE"
                    self._observe("replay", "terminal_tail_complete")
                    self._update_sse_gauges(force=True)
                    return
                if not buffered:
                    self._close_subscriber_locked(tenant_id, subscriber)
                    self._observe("replay", "terminal_tail_gap_drop")
                    return
                target = max(event.sequence for event in buffered)
            try:
                missing = await self._subscription_replay(
                    tenant_id,
                    gap_after,
                    through_sequence=target,
                )
            except LiyanError as exc:
                if exc.code != ErrorCode.SSE_REPLAY_CURSOR_INVALID:
                    raise
                async with self._tenant_locks[tenant_id]:
                    self._close_subscriber_locked(tenant_id, subscriber)
                self._observe("replay", "terminal_tail_retention_drop")
                return
            merged = self._merge_replay_events(tenant_id, merged, missing)
        raise LiyanError(
            ErrorCode.MESSAGE_BUFFER_FULL,
            "The SSE terminal replay tail could not reach a contiguous sequence.",
            category=ErrorCategory.MESSAGING,
            retriable=True,
            status_code=503,
        )

    def _close_subscribers_locked(self, tenant_id: str, outcome: str) -> None:
        dropped = 0
        for subscriber in list(self._subscribers.get(tenant_id, ())):
            if not subscriber.closed:
                self._close_subscriber_locked(tenant_id, subscriber)
                dropped += 1
        self._observe("fanout", outcome, dropped)

    async def _remove_subscriber_cancellation_safe(
        self,
        tenant_id: str,
        subscriber: _Subscriber,
    ) -> None:
        await complete_cleanup(self._remove_subscriber(tenant_id, subscriber))

    async def _remove_subscriber(self, tenant_id: str, subscriber: _Subscriber) -> None:
        background_tasks: list[asyncio.Task[Any]] = []
        async with self._tenant_locks[tenant_id]:
            self._close_subscriber_locked(tenant_id, subscriber)
            subscribers = self._subscribers.get(tenant_id)
            if not subscribers:
                self._subscribers.pop(tenant_id, None)
                self._drop_tenant_caches(tenant_id)
                background_tasks = self._detach_tenant_background_tasks(tenant_id)
                for task in background_tasks:
                    task.cancel()
            self._update_sse_gauges(force=True)
        self._observe("subscribe", "closed")
        if background_tasks:
            await complete_cleanup(asyncio.gather(*background_tasks, return_exceptions=True))

    def _detach_tenant_background_tasks(
        self,
        tenant_id: str,
    ) -> list[asyncio.Task[Any]]:
        current = asyncio.current_task()
        tasks: list[asyncio.Task[Any]] = []
        latest = self._latest_tasks.pop(tenant_id, None)
        if latest is not None and latest is not current and not latest.done():
            tasks.append(latest)
        for key, task in list(self._replay_tasks.items()):
            if key[0] != tenant_id:
                continue
            self._replay_tasks.pop(key, None)
            if task is not current and not task.done():
                tasks.append(task)
        return tasks

    def _close_subscriber_locked(self, tenant_id: str, subscriber: _Subscriber) -> None:
        if subscriber.closed:
            subscribers = self._subscribers.get(tenant_id)
            if subscribers is not None:
                subscribers.discard(subscriber)
            return
        subscriber.closed = True
        self._clear_replay_buffer_locked(subscriber)
        while True:
            try:
                queued = subscriber.queue.get_nowait()
                if isinstance(queued, SSEEvent):
                    self._queued_events = max(0, self._queued_events - 1)
                    self._queued_bytes = max(
                        0,
                        self._queued_bytes - self._event_size(queued),
                    )
            except asyncio.QueueEmpty:
                break
        subscriber.queue.put_nowait(_SUBSCRIBER_CLOSED)
        subscribers = self._subscribers.get(tenant_id)
        if subscribers is not None:
            subscribers.discard(subscriber)

    async def _synchronize_tenant(
        self,
        tenant_id: str,
        *,
        through_sequence: int | None,
        outcome: str,
    ) -> int:
        async with self._synchronize_locks[tenant_id]:
            delivered = 0
            for _page in range(1024):
                async with self._tenant_locks[tenant_id]:
                    live = [
                        subscriber
                        for subscriber in self._active_subscribers(tenant_id)
                        if subscriber.state == "LIVE"
                    ]
                    if not live:
                        return delivered
                    cursor = min(subscriber.last_sequence for subscriber in live)
                    if through_sequence is not None and cursor >= through_sequence:
                        return delivered
                try:
                    events = await self._replay_log.replay(tenant_id, cursor)
                except LiyanError as exc:
                    if exc.code != ErrorCode.SSE_REPLAY_CURSOR_INVALID:
                        raise
                    async with self._tenant_locks[tenant_id]:
                        self._close_subscribers_locked(tenant_id, "retention_gap_drop")
                    return delivered
                if not events:
                    if through_sequence is not None and cursor < through_sequence:
                        raise LiyanError(
                            ErrorCode.MESSAGE_SEQUENCE_GAP,
                            "The notified SSE sequence is not yet visible in durable "
                            "replay storage.",
                            category=ErrorCategory.MESSAGING,
                            retriable=True,
                            status_code=503,
                        )
                    return delivered
                self._validate_replay(tenant_id, events, after_sequence=cursor)
                self._record_durable_event(events[-1])
                async with self._tenant_locks[tenant_id]:
                    delivered += self._fan_out_locked(tenant_id, events)
                self._observe("replay", outcome, len(events))
                if through_sequence is not None and events[-1].sequence >= through_sequence:
                    return delivered
            raise LiyanError(
                ErrorCode.MESSAGE_BUFFER_FULL,
                "The SSE replay page budget was exhausted.",
                category=ErrorCategory.MESSAGING,
                retriable=True,
                status_code=503,
            )

    def _fan_out_locked(
        self,
        tenant_id: str,
        events: list[SSEEvent],
        subscribers: list[_Subscriber] | None = None,
    ) -> int:
        started = perf_counter()
        delivered = 0
        ordered_events = sorted(
            {event.sequence: event for event in events}.values(),
            key=lambda event: event.sequence,
        )
        for event in ordered_events:
            if event.tenant_id != tenant_id:
                raise ValueError("SSE replay returned an event for another tenant")
        targets = list(self._subscribers.get(tenant_id, ())) if subscribers is None else subscribers
        event_sizes = {event.sequence: event.size_bytes for event in ordered_events}
        for subscriber in targets:
            if subscriber.closed:
                self._subscribers[tenant_id].discard(subscriber)
                continue
            if subscriber.state in {"REPLAYING", "DRAINING"}:
                for event in ordered_events:
                    self._buffer_replay_event_locked(tenant_id, subscriber, event)
                continue
            for event in ordered_events:
                if event.sequence <= subscriber.last_sequence:
                    continue
                if event.sequence != subscriber.last_sequence + 1:
                    self._close_subscriber_locked(tenant_id, subscriber)
                    self._observe("fanout", "sequence_gap_drop")
                    break
                if not self._matches_subscriber(subscriber, event):
                    subscriber.last_sequence = event.sequence
                    self._observe("fanout", "filtered")
                    continue
                try:
                    subscriber.queue.put_nowait(event)
                except asyncio.QueueFull:
                    self._close_subscriber_locked(tenant_id, subscriber)
                    self._observe("fanout", "backpressure_drop")
                    break
                subscriber.last_sequence = event.sequence
                self._queued_events += 1
                self._queued_bytes += event_sizes[event.sequence]
                delivered += 1
        self._observe("fanout", "delivered", delivered)
        if self._metrics is not None:
            observer = getattr(self._metrics, "observe_sse_latency", None)
            if observer is not None:
                observer("fanout_locked", max(0.0, perf_counter() - started))
        self._update_sse_gauges()
        return delivered

    @staticmethod
    def _matches_subscriber(subscriber: _Subscriber, event: SSEEvent) -> bool:
        return not subscriber.event_type_prefixes or any(
            event.event_type.startswith(prefix) for prefix in subscriber.event_type_prefixes
        )

    def _buffer_replay_event_locked(
        self,
        tenant_id: str,
        subscriber: _Subscriber,
        event: SSEEvent,
    ) -> None:
        if event.tenant_id != tenant_id or event.sequence <= subscriber.last_sequence:
            return
        existing = subscriber.replay_buffer.get(event.sequence)
        if existing is not None:
            if existing != event:
                self._close_subscriber_locked(tenant_id, subscriber)
                self._observe("fanout", "replay_conflict_drop")
            return
        size_bytes = self._event_size(event)
        if (
            len(subscriber.replay_buffer) >= self._replay_buffer_max_events
            or subscriber.replay_buffer_bytes + size_bytes > self._replay_buffer_max_bytes
        ):
            self._close_subscriber_locked(tenant_id, subscriber)
            self._observe("fanout", "replay_buffer_drop")
            return
        subscriber.replay_buffer[event.sequence] = event
        subscriber.replay_buffer_bytes += size_bytes
        self._replay_buffer_events += 1
        self._replay_buffer_bytes += size_bytes
        self._observe("fanout", "replay_buffered")

    def _clear_replay_buffer_locked(self, subscriber: _Subscriber) -> None:
        self._replay_buffer_events = max(
            0,
            self._replay_buffer_events - len(subscriber.replay_buffer),
        )
        self._replay_buffer_bytes = max(
            0,
            self._replay_buffer_bytes - subscriber.replay_buffer_bytes,
        )
        subscriber.replay_buffer.clear()
        subscriber.replay_buffer_bytes = 0

    @staticmethod
    def _merge_replay_events(
        tenant_id: str,
        *event_groups: list[SSEEvent],
    ) -> list[SSEEvent]:
        merged: dict[int, SSEEvent] = {}
        for events in event_groups:
            for event in events:
                if event.tenant_id != tenant_id:
                    raise ValueError("SSE replay returned an event for another tenant")
                existing = merged.get(event.sequence)
                if existing is not None and existing != event:
                    raise ValueError("SSE replay returned conflicting events for one sequence")
                merged[event.sequence] = event
        return [merged[sequence] for sequence in sorted(merged)]

    @staticmethod
    def _first_sequence_gap(
        events: list[SSEEvent],
        *,
        after_sequence: int | None,
    ) -> int | None:
        if not events:
            return None
        previous = after_sequence
        for index, event in enumerate(events):
            if previous is None and index == 0:
                previous = event.sequence
                continue
            if previous is not None and event.sequence != previous + 1:
                return previous
            previous = event.sequence
        return None

    def _cached_replay(
        self,
        tenant_id: str,
        after_sequence: int | None,
        through_sequence: int | None,
    ) -> list[SSEEvent] | None:
        self._purge_expired_replay_cache()
        tenant_cache = self._replay_cache.get(tenant_id)
        if tenant_cache is None:
            return None
        entry = tenant_cache.get(after_sequence)
        if entry is None:
            return None
        tail = entry.events[-1].sequence if entry.events else after_sequence
        if through_sequence is not None and (tail is None or tail < through_sequence):
            return None
        tenant_cache.move_to_end(after_sequence)
        self._replay_cache.move_to_end(tenant_id)
        return list(entry.events)

    def _store_replay_cache(
        self,
        tenant_id: str,
        after_sequence: int | None,
        events: tuple[SSEEvent, ...],
    ) -> None:
        event_count = len(events)
        size_bytes = sum(self._event_size(event) for event in events)
        if event_count > self._replay_cache_max_events or size_bytes > self._replay_cache_max_bytes:
            return
        self._purge_expired_replay_cache()
        tenant_cache = self._replay_cache.setdefault(tenant_id, OrderedDict())
        previous = tenant_cache.get(after_sequence)
        previous_tail = (
            previous.events[-1].sequence
            if previous is not None and previous.events
            else after_sequence
        )
        new_tail = events[-1].sequence if events else after_sequence
        if (
            previous is not None
            and previous_tail is not None
            and (new_tail is None or previous_tail > new_tail)
        ):
            tenant_cache.move_to_end(after_sequence)
            self._replay_cache.move_to_end(tenant_id)
            return
        previous = tenant_cache.pop(after_sequence, None)
        if previous is not None:
            self._account_replay_cache_removal(previous)
        tenant_cache[after_sequence] = _ReplayCacheEntry(
            events=events,
            expires_at=asyncio.get_running_loop().time() + self._replay_cache_seconds,
            size_bytes=size_bytes,
        )
        self._replay_cache_events += event_count
        self._replay_cache_bytes += size_bytes
        while len(tenant_cache) > 8:
            _, evicted = tenant_cache.popitem(last=False)
            self._account_replay_cache_removal(evicted)
        self._replay_cache.move_to_end(tenant_id)
        while len(self._replay_cache) > self._replay_cache_max_tenants:
            _, evicted_cache = self._replay_cache.popitem(last=False)
            for entry in evicted_cache.values():
                self._account_replay_cache_removal(entry)
        while (
            self._replay_cache_events > self._replay_cache_max_events
            or self._replay_cache_bytes > self._replay_cache_max_bytes
        ) and self._replay_cache:
            oldest_tenant = next(iter(self._replay_cache))
            oldest_cache = self._replay_cache[oldest_tenant]
            _, evicted = oldest_cache.popitem(last=False)
            self._account_replay_cache_removal(evicted)
            if not oldest_cache:
                self._replay_cache.pop(oldest_tenant, None)
        self._schedule_replay_cache_expiry()
        self._update_sse_gauges()

    def _purge_expired_replay_cache(self) -> None:
        now = asyncio.get_running_loop().time()
        for tenant_id, tenant_cache in list(self._replay_cache.items()):
            for cursor, entry in list(tenant_cache.items()):
                if entry.expires_at <= now:
                    tenant_cache.pop(cursor, None)
                    self._account_replay_cache_removal(entry)
            if not tenant_cache:
                self._replay_cache.pop(tenant_id, None)
        if not self._replay_cache and self._replay_cache_expiry_handle is not None:
            self._replay_cache_expiry_handle.cancel()
            self._replay_cache_expiry_handle = None

    def _drop_tenant_replay_cache(self, tenant_id: str) -> None:
        cache = self._replay_cache.pop(tenant_id, None)
        if cache is not None:
            for entry in cache.values():
                self._account_replay_cache_removal(entry)
        self._schedule_replay_cache_expiry()

    def _schedule_replay_cache_expiry(self) -> None:
        handle = self._replay_cache_expiry_handle
        if handle is not None:
            handle.cancel()
            self._replay_cache_expiry_handle = None
        expirations = [
            entry.expires_at
            for tenant_cache in self._replay_cache.values()
            for entry in tenant_cache.values()
        ]
        if not expirations:
            return
        loop = asyncio.get_running_loop()
        delay = max(0.0, min(expirations) - loop.time())
        self._replay_cache_expiry_handle = loop.call_later(
            delay,
            self._expire_replay_cache,
        )

    def _expire_replay_cache(self) -> None:
        self._replay_cache_expiry_handle = None
        self._purge_expired_replay_cache()
        self._schedule_replay_cache_expiry()
        self._update_sse_gauges(force=True)

    def _account_replay_cache_removal(self, entry: _ReplayCacheEntry) -> None:
        self._replay_cache_events = max(
            0,
            self._replay_cache_events - len(entry.events),
        )
        self._replay_cache_bytes = max(0, self._replay_cache_bytes - entry.size_bytes)

    def _cached_latest_sequence(self, tenant_id: str) -> tuple[bool, int | None]:
        now = asyncio.get_running_loop().time()
        entry = self._latest_cache.get(tenant_id)
        if entry is None:
            return False, None
        if entry.expires_at <= now:
            self._latest_cache.pop(tenant_id, None)
            return False, None
        self._latest_cache.move_to_end(tenant_id)
        return True, entry.sequence

    def _store_latest_sequence(self, tenant_id: str, sequence: int | None) -> int | None:
        existing = self._latest_cache.get(tenant_id)
        if existing is not None and (
            sequence is None or (existing.sequence is not None and existing.sequence > sequence)
        ):
            sequence = existing.sequence
        self._latest_cache[tenant_id] = _LatestCacheEntry(
            sequence=sequence,
            expires_at=asyncio.get_running_loop().time() + self._replay_cache_seconds,
        )
        self._latest_cache.move_to_end(tenant_id)
        while len(self._latest_cache) > self._replay_cache_max_tenants:
            self._latest_cache.popitem(last=False)
        return sequence

    def _record_durable_event(self, event: SSEEvent) -> None:
        self._drop_tenant_replay_cache(event.tenant_id)
        self._store_latest_sequence(event.tenant_id, event.sequence)
        self._update_sse_gauges()

    def _drop_tenant_caches(self, tenant_id: str) -> None:
        self._drop_tenant_replay_cache(tenant_id)
        self._latest_cache.pop(tenant_id, None)

    @staticmethod
    def _event_size(event: SSEEvent) -> int:
        return event.size_bytes

    def _event_dequeued(self, event: SSEEvent | _SubscriberClosed) -> None:
        self._queued_events = max(0, self._queued_events - 1)
        if isinstance(event, SSEEvent):
            self._queued_bytes = max(0, self._queued_bytes - self._event_size(event))
        if isinstance(event, SSEEvent) and self._metrics is not None:
            observer = getattr(self._metrics, "observe_sse_latency", None)
            if observer is not None:
                observer(
                    "published_to_client",
                    max(0.0, (datetime.now(UTC) - event.emitted_at).total_seconds()),
                )
        self._update_sse_gauges()

    def _subscription_close_started(self) -> None:
        self._closing_subscriptions += 1
        self._update_sse_gauges(force=True)

    def _subscription_close_finished(self) -> None:
        self._closing_subscriptions = max(0, self._closing_subscriptions - 1)
        self._update_sse_gauges(force=True)

    def _update_sse_gauges(self, *, force: bool = False) -> None:
        if self._metrics is None:
            return
        now = asyncio.get_running_loop().time()
        if not force and now < self._next_gauge_update_at:
            return
        self._next_gauge_update_at = now + self._gauge_update_interval_seconds
        setter = getattr(self._metrics, "set_sse_gauge", None)
        if setter is None:
            return
        subscribers = [
            subscriber
            for items in self._subscribers.values()
            for subscriber in items
            if not subscriber.closed
        ]
        setter("subscribers", len(subscribers))
        setter("subscribers_live", sum(item.state == "LIVE" for item in subscribers))
        setter(
            "subscribers_replaying",
            sum(item.state == "REPLAYING" for item in subscribers),
        )
        setter(
            "subscribers_draining",
            sum(item.state == "DRAINING" for item in subscribers),
        )
        setter("queued_events", self._queued_events)
        setter("queued_bytes", self._queued_bytes)
        setter("replay_buffer_events", self._replay_buffer_events)
        setter("replay_buffer_bytes", self._replay_buffer_bytes)
        setter("replay_cache_tenants", len(self._replay_cache))
        setter("replay_cache_events", self._replay_cache_events)
        setter("replay_cache_bytes", self._replay_cache_bytes)
        setter("replay_tasks", len(self._replay_tasks) + len(self._latest_tasks))
        setter("closing_subscriptions", self._closing_subscriptions)

    @staticmethod
    def _validate_replay(
        tenant_id: str,
        events: list[SSEEvent],
        *,
        after_sequence: int | None,
    ) -> None:
        previous = after_sequence
        for event in events:
            if event.tenant_id != tenant_id:
                raise ValueError("SSE replay returned an event for another tenant")
            if previous is not None and event.sequence != previous + 1:
                raise ValueError("SSE replay returned a noncontiguous sequence")
            previous = event.sequence

    def _observe(self, operation: str, outcome: str, count: int = 1) -> None:
        if self._metrics is not None and count > 0:
            self._metrics.observe_sse(operation, outcome, count)

    def _observe_latency(self, stage: str, started_at: float) -> None:
        if self._metrics is None:
            return
        observer = getattr(self._metrics, "observe_sse_latency", None)
        if observer is not None:
            observer(stage, max(0.0, asyncio.get_running_loop().time() - started_at))

    @staticmethod
    def _admission_failure_outcome(exc: LiyanError) -> str:
        if exc.code == ErrorCode.SSE_REPLAY_CURSOR_INVALID:
            return "cursor_rejected"
        if exc.code == ErrorCode.MESSAGE_SEQUENCE_GAP:
            return "replay_gap"
        if exc.code == ErrorCode.MESSAGE_BUFFER_FULL:
            return "capacity_rejected"
        return "retriable_failure" if exc.retriable else "rejected"


def encode_sse_frame(event: SSEEvent, cursor: str) -> bytes:
    return b"id: " + cursor.encode("ascii") + b"\n" + event.frame_body
