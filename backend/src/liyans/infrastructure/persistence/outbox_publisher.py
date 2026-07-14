from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.infrastructure.messaging.bus import AsyncMessageBus, DispatchStatus
from liyans.infrastructure.persistence.outbox import (
    OutboxDispatchRepository,
    OutboxMessage,
)

logger = logging.getLogger(__name__)
OutboxSink = Callable[[OutboxMessage], Awaitable[None]]


class OutboxMetricsObserver(Protocol):
    def observe_outbox(self, operation: str, outcome: str, count: int = 1) -> None: ...


class MessageBusOutboxSink:
    def __init__(
        self,
        message_bus: AsyncMessageBus,
        repository: OutboxDispatchRepository,
    ) -> None:
        self._message_bus = message_bus
        self._repository = repository

    async def __call__(self, message: OutboxMessage) -> None:
        envelope = message.envelope
        if envelope.tenant_id != message.tenant_id:
            raise ValueError("Outbox and Envelope tenant identities do not match")
        context = TenantContext(
            tenant_id=message.tenant_id,
            subject_ref=envelope.subject_ref,
            roles=frozenset({"system:outbox-dispatcher"}),
            scopes=frozenset({"topic3:dispatch"}),
            trace_id=envelope.trace_id,
            session_id=envelope.session_id,
        )
        with tenant_scope(context):
            cursor = await self._repository.published_cursor(
                message.tenant_id,
                envelope.partition_key,
            )
            if envelope.sequence != cursor:
                raise LiyanError(
                    ErrorCode.MESSAGE_SEQUENCE_GAP,
                    "The Outbox partition does not have a contiguous durable cursor.",
                    category=ErrorCategory.MESSAGING,
                    retriable=True,
                    status_code=409,
                )
            self._message_bus.restore_partition_cursor(
                message.tenant_id,
                envelope.partition_key,
                cursor,
            )
            result = await self._message_bus.publish(envelope)
            if result.status in {DispatchStatus.BUFFERED, DispatchStatus.IN_FLIGHT}:
                raise LiyanError(
                    ErrorCode.MESSAGE_SEQUENCE_GAP,
                    "The Outbox delivery was not durably completed by the consumer.",
                    category=ErrorCategory.MESSAGING,
                    retriable=True,
                    status_code=409,
                )


class OutboxPublisher:
    def __init__(
        self,
        repository: OutboxDispatchRepository,
        sink: OutboxSink,
        *,
        worker_id: str,
        batch_size: int = 32,
        poll_interval_seconds: float = 0.5,
        retry_base_seconds: float = 0.25,
        retry_max_seconds: float = 30.0,
        metrics: OutboxMetricsObserver | None = None,
    ) -> None:
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id must contain between one and 128 characters")
        if not 1 <= batch_size <= 1000:
            raise ValueError("batch_size must be between one and 1000")
        if min(poll_interval_seconds, retry_base_seconds, retry_max_seconds) <= 0:
            raise ValueError("publisher timing settings must be positive")
        self._repository = repository
        self._sink = sink
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._poll_interval = poll_interval_seconds
        self._retry_base = retry_base_seconds
        self._retry_max = retry_max_seconds
        self._metrics = metrics
        self._stopping = asyncio.Event()
        self._wake = asyncio.Event()
        self._ready = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def healthy(self) -> bool:
        return self.running and self._ready.is_set() and self._last_error is None

    async def start(self) -> None:
        if self.running:
            return
        self._stopping.clear()
        self._ready.clear()
        self._task = asyncio.create_task(self._run(), name=f"outbox:{self._worker_id}")

    async def close(self) -> None:
        self._stopping.set()
        self._wake.set()
        task = self._task
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=max(5.0, self._poll_interval * 2))
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        finally:
            self._task = None
            self._ready.clear()

    def wake(self) -> None:
        self._wake.set()

    async def run_once(self) -> int:
        messages = await self._repository.claim_batch(self._worker_id, self._batch_size)
        self._ready.set()
        if not messages:
            self._observe("claim", "empty")
            return 0
        self._observe("claim", "claimed", len(messages))
        await asyncio.gather(*(self._process(message) for message in messages))
        return len(messages)

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                processed = await self.run_once()
                self._last_error = None
            except Exception as exc:
                self._last_error = type(exc).__name__
                self._observe("claim", "failed")
                logger.exception("Outbox claim loop failed worker=%s", self._worker_id)
                processed = 0
            if processed:
                continue
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval)
            except TimeoutError:
                continue

    async def _process(self, message: OutboxMessage) -> None:
        try:
            await self._sink(message)
            await self._repository.mark_published(
                message.outbox_id,
                self._worker_id,
                datetime.now(UTC),
            )
            self._observe("delivery", "published")
        except Exception as exc:
            error_code = exc.code.value if isinstance(exc, LiyanError) else type(exc).__name__
            delay = min(
                self._retry_max,
                self._retry_base * (2 ** max(0, message.attempts - 1)),
            )
            await self._repository.release_claim(
                message.outbox_id,
                self._worker_id,
                datetime.now(UTC) + timedelta(seconds=delay),
                error_code=error_code[:128],
            )
            outcome = "dead" if message.attempts >= message.max_attempts else "retry"
            self._observe("delivery", outcome)
            logger.warning(
                "Outbox delivery failed outbox_id=%s attempt=%s error_code=%s",
                message.outbox_id,
                message.attempts,
                error_code,
            )

    def _observe(self, operation: str, outcome: str, count: int = 1) -> None:
        if self._metrics is not None and count > 0:
            self._metrics.observe_outbox(operation, outcome, count)
