from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import re
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from liyans_contracts.topic3 import SSEChunkV1, StreamFragmentType

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


class ReplayCursorCodec:
    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("SSE cursor secret must contain at least 32 bytes")
        self._secret = secret

    def encode(self, tenant_id: str, sequence: int) -> str:
        if not tenant_id or sequence < 0:
            raise ValueError("SSE cursor tenant and nonnegative sequence are required")
        payload = f"{tenant_id}:{sequence}".encode()
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + b"." + signature).decode("ascii").rstrip("=")

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


@dataclass(eq=False, slots=True)
class _Subscriber:
    queue: asyncio.Queue[SSEEvent]
    last_sequence: int
    closed: bool = False


class SSEBroker:
    def __init__(
        self,
        replay_log: SSEReplayLog,
        *,
        subscriber_queue_size: int = 128,
        metrics: SSEMetricsObserver | None = None,
    ) -> None:
        if subscriber_queue_size < 1:
            raise ValueError("subscriber_queue_size must be positive")
        self._replay_log = replay_log
        self._subscriber_queue_size = subscriber_queue_size
        self._metrics = metrics
        self._subscribers: dict[str, set[_Subscriber]] = defaultdict(set)
        self._tenant_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def publish(self, tenant_id: str, event_type: str, data: dict[str, Any]) -> SSEEvent:
        event = await self._replay_log.append(tenant_id, event_type, data)
        self._observe("publish", "persisted")
        await self.deliver(event)
        return event

    async def deliver(self, event: SSEEvent) -> int:
        """Fan out a committed event, replaying any detected sequence gap first."""

        if event.sequence < 0 or event.emitted_at.tzinfo is None:
            raise ValueError("SSE events require a nonnegative sequence and aware timestamp")
        tenant_id = event.tenant_id
        async with self._tenant_locks[tenant_id]:
            subscribers = self._active_subscribers(tenant_id)
            if not subscribers:
                return 0
            minimum_cursor = min(subscriber.last_sequence for subscriber in subscribers)
            if event.sequence > minimum_cursor + 1:
                return await self._replay_pages_locked(
                    tenant_id,
                    minimum_cursor,
                    through_sequence=event.sequence,
                    outcome="gap_recovered",
                )
            return self._fan_out_locked(tenant_id, [event])

    async def synchronize(self, tenant_id: str, *, through_sequence: int | None = None) -> int:
        """Close notification loss/reconnect gaps from the durable replay log."""

        if through_sequence is not None and through_sequence < 0:
            raise ValueError("through_sequence cannot be negative")
        async with self._tenant_locks[tenant_id]:
            subscribers = self._active_subscribers(tenant_id)
            if not subscribers:
                return 0
            minimum_cursor = min(subscriber.last_sequence for subscriber in subscribers)
            if through_sequence is not None and minimum_cursor >= through_sequence:
                return 0
            return await self._replay_pages_locked(
                tenant_id,
                minimum_cursor,
                through_sequence=through_sequence,
                outcome="notification_sync",
            )

    def active_tenants(self) -> tuple[str, ...]:
        return tuple(
            tenant_id
            for tenant_id, subscribers in self._subscribers.items()
            if any(not subscriber.closed for subscriber in subscribers)
        )

    async def subscribe(
        self,
        tenant_id: str,
        *,
        after_sequence: int | None = None,
        heartbeat_seconds: float = 15.0,
    ) -> AsyncIterator[SSEEvent | None]:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        if after_sequence is not None and after_sequence < 0:
            raise ValueError("after_sequence cannot be negative")
        async with self._tenant_locks[tenant_id]:
            replay = await self._replay_log.replay(tenant_id, after_sequence)
            self._validate_replay(tenant_id, replay, after_sequence=after_sequence)
            last_sequence = after_sequence if after_sequence is not None else -1
            if replay:
                last_sequence = replay[-1].sequence
            elif after_sequence is None:
                latest_sequence = await self._replay_log.latest_sequence(tenant_id)
                if latest_sequence is not None:
                    last_sequence = latest_sequence
            subscriber = _Subscriber(
                asyncio.Queue(maxsize=self._subscriber_queue_size),
                last_sequence=last_sequence,
            )
            self._subscribers[tenant_id].add(subscriber)
        self._observe("subscribe", "opened")
        self._observe("replay", "subscriber_replay", len(replay))
        for event in replay:
            yield event
        try:
            while not subscriber.closed:
                try:
                    event = await asyncio.wait_for(
                        subscriber.queue.get(),
                        timeout=heartbeat_seconds,
                    )
                except TimeoutError:
                    yield None
                    continue
                yield event
        finally:
            async with self._tenant_locks[tenant_id]:
                self._subscribers[tenant_id].discard(subscriber)
                if not self._subscribers[tenant_id]:
                    self._subscribers.pop(tenant_id, None)
            self._observe("subscribe", "closed")

    def _active_subscribers(self, tenant_id: str) -> list[_Subscriber]:
        return [subscriber for subscriber in self._subscribers[tenant_id] if not subscriber.closed]

    def _close_subscribers_locked(self, tenant_id: str, outcome: str) -> None:
        dropped = 0
        for subscriber in list(self._subscribers[tenant_id]):
            if not subscriber.closed:
                subscriber.closed = True
                dropped += 1
            self._subscribers[tenant_id].discard(subscriber)
        self._observe("fanout", outcome, dropped)

    async def _replay_pages_locked(
        self,
        tenant_id: str,
        after_sequence: int,
        *,
        through_sequence: int | None,
        outcome: str,
    ) -> int:
        delivered = 0
        cursor = after_sequence
        for _page in range(1024):
            try:
                events = await self._replay_log.replay(tenant_id, cursor)
            except LiyanError as exc:
                if exc.code != ErrorCode.SSE_REPLAY_CURSOR_INVALID:
                    raise
                self._close_subscribers_locked(tenant_id, "retention_gap_drop")
                return delivered
            if not events:
                if through_sequence is not None and cursor < through_sequence:
                    raise LiyanError(
                        ErrorCode.MESSAGE_SEQUENCE_GAP,
                        "The notified SSE sequence is not yet visible in durable replay storage.",
                        category=ErrorCategory.MESSAGING,
                        retriable=True,
                        status_code=503,
                    )
                return delivered
            self._validate_replay(tenant_id, events, after_sequence=cursor)
            delivered += self._fan_out_locked(tenant_id, events)
            self._observe("replay", outcome, len(events))
            cursor = events[-1].sequence
            if through_sequence is not None and cursor >= through_sequence:
                return delivered
            if not self._active_subscribers(tenant_id):
                return delivered
        raise LiyanError(
            ErrorCode.MESSAGE_BUFFER_FULL,
            "The SSE replay page budget was exhausted.",
            category=ErrorCategory.MESSAGING,
            retriable=True,
            status_code=503,
        )

    def _fan_out_locked(self, tenant_id: str, events: list[SSEEvent]) -> int:
        delivered = 0
        ordered_events = sorted(
            {event.sequence: event for event in events}.values(),
            key=lambda event: event.sequence,
        )
        for event in ordered_events:
            if event.tenant_id != tenant_id:
                raise ValueError("SSE replay returned an event for another tenant")
        for subscriber in list(self._subscribers[tenant_id]):
            if subscriber.closed:
                self._subscribers[tenant_id].discard(subscriber)
                continue
            for event in ordered_events:
                if event.sequence <= subscriber.last_sequence:
                    continue
                if event.sequence != subscriber.last_sequence + 1:
                    subscriber.closed = True
                    self._subscribers[tenant_id].discard(subscriber)
                    self._observe("fanout", "sequence_gap_drop")
                    break
                try:
                    subscriber.queue.put_nowait(event)
                except asyncio.QueueFull:
                    subscriber.closed = True
                    self._subscribers[tenant_id].discard(subscriber)
                    self._observe("fanout", "backpressure_drop")
                    break
                subscriber.last_sequence = event.sequence
                delivered += 1
        self._observe("fanout", "delivered", delivered)
        return delivered

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


def encode_sse_frame(event: SSEEvent, cursor: str) -> bytes:
    data = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"))
    lines = [f"id: {cursor}", f"event: {event.event_type}"]
    lines.extend(f"data: {line}" for line in data.splitlines() or [""])
    return ("\n".join(lines) + "\n\n").encode("utf-8")
