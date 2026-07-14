from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from liyans_contracts.envelope import Topic3EnvelopeV1

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError, MessageSequenceError
from liyans.core.hashing import sha256_hex
from liyans.infrastructure.messaging.idempotency import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    ReservationDecision,
)
from liyans.infrastructure.messaging.middleware import MessageMiddleware, compose_middleware

logger = logging.getLogger(__name__)

MessageHandler = Callable[[Topic3EnvelopeV1], Awaitable[None]]
FailureHandler = Callable[[Topic3EnvelopeV1, Exception], Awaitable[None]]


class DispatchStatus(StrEnum):
    PROCESSED = "PROCESSED"
    BUFFERED = "BUFFERED"
    DUPLICATE = "DUPLICATE"
    IN_FLIGHT = "IN_FLIGHT"


@dataclass(frozen=True, slots=True)
class DispatchResult:
    status: DispatchStatus
    partition_key: str
    sequence: int
    next_expected_sequence: int


def delivery_digest(envelope: Topic3EnvelopeV1) -> str:
    """Hash immutable message meaning while excluding retry-mutated delivery fields."""

    document = envelope.model_dump(mode="json")
    document["delivery"]["attempt"] = 1
    document["delivery"]["available_at"] = document["created_at"]
    return sha256_hex(document)


class AsyncMessageBus:
    def __init__(
        self,
        *,
        idempotency_store: IdempotencyStore | None = None,
        middleware: list[MessageMiddleware] | None = None,
        max_gap_buffer_per_partition: int = 256,
        failure_handler: FailureHandler | None = None,
    ) -> None:
        if max_gap_buffer_per_partition < 1:
            raise ValueError("max_gap_buffer_per_partition must be positive")
        self._idempotency = idempotency_store or InMemoryIdempotencyStore()
        self._middleware = list(middleware or [])
        self._max_gap_buffer = max_gap_buffer_per_partition
        self._failure_handler = failure_handler
        self._handlers: dict[str, list[MessageHandler]] = defaultdict(list)
        self._expected: dict[tuple[str, str], int] = defaultdict(int)
        self._pending: dict[tuple[str, str], dict[int, tuple[Topic3EnvelopeV1, str]]] = defaultdict(
            dict
        )
        self._partition_locks: dict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def register(self, event_type: str, handler: MessageHandler) -> None:
        if self._closed:
            raise RuntimeError("message bus is closed")
        if handler in self._handlers[event_type]:
            raise ValueError(f"handler already registered for {event_type}")
        self._handlers[event_type].append(handler)

    def restore_partition_cursor(
        self,
        tenant_id: str,
        partition_key: str,
        next_expected_sequence: int,
    ) -> None:
        """Restore a durable cursor before dispatching a reclaimed Outbox message."""
        if not tenant_id or not partition_key:
            raise ValueError("tenant_id and partition_key are required")
        if next_expected_sequence < 0:
            raise ValueError("next_expected_sequence cannot be negative")
        partition = (tenant_id, partition_key)
        if self._pending.get(partition):
            raise RuntimeError("cannot restore a partition while gap-buffered messages exist")
        current = self._expected.get(partition, 0)
        if next_expected_sequence < current:
            raise RuntimeError("cannot move a partition cursor backwards")
        self._expected[partition] = next_expected_sequence

    async def close(self) -> None:
        self._closed = True

    async def publish(self, envelope: Topic3EnvelopeV1) -> DispatchResult:
        if self._closed:
            raise LiyanError(
                ErrorCode.INTERNAL,
                "The message bus is closed.",
                category=ErrorCategory.MESSAGING,
                status_code=503,
            )
        self._assert_not_expired(envelope)
        digest = delivery_digest(envelope)
        partition_key = envelope.partition_key
        partition = (envelope.tenant_id, partition_key)

        async with self._partition_locks[partition]:
            expected = self._expected[partition]
            decision = await self._idempotency.reserve(
                envelope.delivery.idempotency_key,
                digest,
            )
            if decision != ReservationDecision.RESERVED:
                status = (
                    DispatchStatus.DUPLICATE
                    if decision == ReservationDecision.DUPLICATE_COMPLETED
                    else DispatchStatus.IN_FLIGHT
                )
                return DispatchResult(
                    status=status,
                    partition_key=partition_key,
                    sequence=envelope.sequence,
                    next_expected_sequence=expected,
                )

            if envelope.sequence < expected:
                await self._idempotency.abort(envelope.delivery.idempotency_key, digest)
                raise MessageSequenceError(
                    ErrorCode.MESSAGE_SEQUENCE_STALE,
                    "The message sequence is older than the committed partition cursor.",
                )

            if envelope.sequence > expected:
                pending = self._pending[partition]
                if len(pending) >= self._max_gap_buffer:
                    await self._idempotency.abort(envelope.delivery.idempotency_key, digest)
                    raise LiyanError(
                        ErrorCode.MESSAGE_BUFFER_FULL,
                        "The partition ordering buffer is full.",
                        category=ErrorCategory.MESSAGING,
                        retriable=True,
                        status_code=503,
                    )
                existing = pending.get(envelope.sequence)
                if existing is not None:
                    await self._idempotency.abort(envelope.delivery.idempotency_key, digest)
                    raise MessageSequenceError(
                        ErrorCode.MESSAGE_SEQUENCE_GAP,
                        "A different message already occupies the buffered sequence.",
                    )
                pending[envelope.sequence] = (envelope, digest)
                return DispatchResult(
                    status=DispatchStatus.BUFFERED,
                    partition_key=partition_key,
                    sequence=envelope.sequence,
                    next_expected_sequence=expected,
                )

            await self._execute_reserved(envelope, digest)
            self._expected[partition] += 1
            await self._drain_partition(partition)
            return DispatchResult(
                status=DispatchStatus.PROCESSED,
                partition_key=partition_key,
                sequence=envelope.sequence,
                next_expected_sequence=self._expected[partition],
            )

    async def _drain_partition(self, partition: tuple[str, str]) -> None:
        pending = self._pending[partition]
        while self._expected[partition] in pending:
            sequence = self._expected[partition]
            envelope, digest = pending.pop(sequence)
            try:
                await self._execute_reserved(envelope, digest)
            except Exception:
                return
            self._expected[partition] += 1

    async def _execute_reserved(self, envelope: Topic3EnvelopeV1, digest: str) -> None:
        key = envelope.delivery.idempotency_key
        await self._idempotency.mark_processing(key, digest)
        handler = compose_middleware(self._middleware, self._dispatch_handlers)
        try:
            await handler(envelope)
        except Exception as exc:
            await self._idempotency.abort(key, digest)
            if self._failure_handler is not None:
                try:
                    await self._failure_handler(envelope, exc)
                except Exception:
                    logger.exception(
                        "Message failure handler failed for envelope %s",
                        envelope.envelope_id,
                    )
            raise
        await self._idempotency.complete(key, digest)

    async def _dispatch_handlers(self, envelope: Topic3EnvelopeV1) -> None:
        handlers = self._handlers.get(envelope.event_type, [])
        if not handlers:
            raise LiyanError(
                ErrorCode.MESSAGE_HANDLER_MISSING,
                "No message handler is registered for the event type.",
                category=ErrorCategory.MESSAGING,
                status_code=422,
                details={"event_type": envelope.event_type},
            )
        for handler in handlers:
            await handler(envelope)

    @staticmethod
    def _assert_not_expired(envelope: Topic3EnvelopeV1) -> None:
        expires_at = envelope.delivery.expires_at
        if expires_at is not None and expires_at <= datetime.now(UTC):
            raise LiyanError(
                ErrorCode.MESSAGE_EXPIRED,
                "The message expired before dispatch.",
                category=ErrorCategory.MESSAGING,
                status_code=410,
            )
