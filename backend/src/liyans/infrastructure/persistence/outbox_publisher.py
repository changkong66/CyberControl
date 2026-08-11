from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Protocol

from liyans.core.async_cleanup import complete_cleanup
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

    def observe_outbox_latency(self, stage: str, duration_seconds: float) -> None: ...

    def set_outbox_gauge(self, metric: str, value: int) -> None: ...


class MessageBusOutboxSink:
    def __init__(
        self,
        message_bus: AsyncMessageBus,
        repository: OutboxDispatchRepository,
        *,
        metrics: OutboxMetricsObserver | None = None,
    ) -> None:
        self._message_bus = message_bus
        self._repository = repository
        self._metrics = metrics

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
            dispatch_started = datetime.now(UTC)
            if message.claimed_at is not None:
                self._observe_latency(
                    "claimed_to_dispatch_start",
                    message.claimed_at,
                    dispatch_started,
                )
            cursor = message.published_cursor
            if cursor is None:
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
            started = perf_counter()
            try:
                result = await self._message_bus.publish(envelope)
            except LiyanError as exc:
                outcome = "forbidden" if exc.code == ErrorCode.AUTH_FORBIDDEN else "rejected"
                self._observe("authorization", outcome)
                raise
            if result.status in {DispatchStatus.BUFFERED, DispatchStatus.IN_FLIGHT}:
                self._observe("authorization", "not_durable")
                raise LiyanError(
                    ErrorCode.MESSAGE_SEQUENCE_GAP,
                    "The Outbox delivery was not durably completed by the consumer.",
                    category=ErrorCategory.MESSAGING,
                    retriable=True,
                    status_code=409,
                )
            self._observe("authorization", "accepted")
            self._observe_duration(
                "dispatch_to_durable_acceptance",
                perf_counter() - started,
            )

    def _observe(self, operation: str, outcome: str) -> None:
        if self._metrics is not None:
            self._metrics.observe_outbox(operation, outcome)

    def _observe_latency(
        self,
        stage: str,
        started_at: datetime,
        completed_at: datetime,
    ) -> None:
        self._observe_duration(stage, (completed_at - started_at).total_seconds())

    def _observe_duration(self, stage: str, duration_seconds: float) -> None:
        if self._metrics is not None:
            self._metrics.observe_outbox_latency(stage, max(0.0, duration_seconds))


class OutboxPublisher:
    def __init__(
        self,
        repository: OutboxDispatchRepository,
        sink: OutboxSink,
        *,
        worker_id: str,
        batch_size: int = 32,
        poll_interval_seconds: float = 0.5,
        delivery_timeout_seconds: float = 25.0,
        retry_base_seconds: float = 0.25,
        retry_max_seconds: float = 30.0,
        metrics: OutboxMetricsObserver | None = None,
    ) -> None:
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id must contain between one and 128 characters")
        if not 1 <= batch_size <= 1000:
            raise ValueError("batch_size must be between one and 1000")
        if (
            min(
                poll_interval_seconds,
                delivery_timeout_seconds,
                retry_base_seconds,
                retry_max_seconds,
            )
            <= 0
        ):
            raise ValueError("publisher timing settings must be positive")
        self._repository = repository
        self._sink = sink
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._poll_interval = poll_interval_seconds
        self._delivery_timeout = delivery_timeout_seconds
        self._retry_base = retry_base_seconds
        self._retry_max = retry_max_seconds
        self._metrics = metrics
        self._stopping = asyncio.Event()
        self._wake = asyncio.Event()
        self._ready = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_error: str | None = None
        self._in_flight = 0

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
        claim_started = perf_counter()
        messages = await self._repository.claim_batch(self._worker_id, self._batch_size)
        self._observe_duration("claim_batch", perf_counter() - claim_started)
        self._ready.set()
        if not messages:
            self._observe("claim", "empty")
            return 0
        self._observe("claim", "claimed", len(messages))
        for message in messages:
            if message.claimed_at is not None:
                self._observe_latency(
                    "created_to_claimable",
                    message.created_at,
                    message.available_at,
                )
                self._observe_latency(
                    "claimable_to_claimed",
                    message.available_at,
                    message.claimed_at,
                )
                self._observe_latency(
                    "created_to_claimed",
                    message.created_at,
                    message.claimed_at,
                )
        partitions: dict[tuple[str, str], list[OutboxMessage]] = defaultdict(list)
        for message in messages:
            partitions[(message.tenant_id, message.envelope.partition_key)].append(message)
        results = await asyncio.gather(
            *(self._process_partition(items) for items in partitions.values()),
            return_exceptions=True,
        )
        failure = next(
            (result for result in results if isinstance(result, BaseException)),
            None,
        )
        if failure is not None:
            raise failure
        return len(messages)

    async def _process_partition(self, messages: list[OutboxMessage]) -> None:
        ordered = sorted(messages, key=lambda message: message.envelope.sequence)
        lease_expires_at = min(
            (
                message.claim_expires_at
                for message in ordered
                if message.claim_expires_at is not None
            ),
            default=None,
        )
        for index, message in enumerate(ordered):
            remaining = ordered[index:]
            if self._claim_renewal_required(lease_expires_at):
                try:
                    lease_expires_at = await self._repository.renew_claims(
                        tuple(item.outbox_id for item in remaining),
                        self._worker_id,
                    )
                    self._observe("claim", "lease_renewed", len(remaining))
                except Exception:
                    await self._release_partition_tail(
                        remaining,
                        error_code="LeaseRenewalFailed",
                    )
                    raise
            try:
                published = await self._process(message)
            except asyncio.CancelledError:
                await complete_cleanup(
                    self._release_partition_tail(
                        ordered[index + 1 :],
                        error_code="CancelledError",
                    )
                )
                raise
            if not published:
                await self._release_partition_tail(
                    ordered[index + 1 :],
                    error_code="PartitionBlocked",
                )
                return

    async def _release_partition_tail(
        self,
        messages: list[OutboxMessage],
        *,
        error_code: str,
    ) -> None:
        if not messages:
            return
        available_at = datetime.now(UTC)
        results = await asyncio.gather(
            *(
                self._repository.release_claim(
                    message.outbox_id,
                    self._worker_id,
                    available_at,
                    error_code=error_code,
                    restore_attempt=True,
                )
                for message in messages
            ),
            return_exceptions=True,
        )
        released = sum(not isinstance(result, BaseException) for result in results)
        failures = len(results) - released
        self._observe("delivery", "partition_tail_released", released)
        self._observe("delivery", "claim_release_failed", failures)
        if failures:
            logger.warning(
                "Outbox partition tail release was incomplete worker=%s failures=%s",
                self._worker_id,
                failures,
            )

    def _claim_renewal_required(self, claim_expires_at: datetime | None) -> bool:
        if claim_expires_at is None:
            return False
        safety_seconds = min(1.0, max(0.1, self._delivery_timeout * 0.1))
        required_until = datetime.now(UTC) + timedelta(
            seconds=self._delivery_timeout + safety_seconds
        )
        return claim_expires_at <= required_until

    async def _run(self) -> None:
        while not self._stopping.is_set():
            self._wake.clear()
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
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval)
            except TimeoutError:
                continue

    async def _process(self, message: OutboxMessage) -> bool:
        self._in_flight += 1
        self._update_gauges()
        dispatch_started = perf_counter()
        try:
            await asyncio.wait_for(
                self._sink(message),
                timeout=self._delivery_timeout,
            )
            published_at = datetime.now(UTC)
            await self._repository.mark_published(
                message.outbox_id,
                self._worker_id,
                published_at,
            )
            if message.claimed_at is not None:
                self._observe_latency(
                    "claimed_to_published",
                    message.claimed_at,
                    published_at,
                )
            self._observe_latency(
                "created_to_published",
                message.created_at,
                published_at,
            )
            self._observe_duration(
                "dispatch_to_published",
                perf_counter() - dispatch_started,
            )
            self._observe("delivery", "published")
            return True
        except asyncio.CancelledError:
            await complete_cleanup(
                self._release_claim_safely(
                    message,
                    available_at=datetime.now(UTC),
                    error_code="CancelledError",
                )
            )
            self._observe("delivery", "cancelled")
            raise
        except Exception as exc:
            error_code = exc.code.value if isinstance(exc, LiyanError) else type(exc).__name__
            classification = (
                "authorization"
                if isinstance(exc, LiyanError) and exc.code == ErrorCode.AUTH_FORBIDDEN
                else "transient"
                if isinstance(exc, LiyanError) and exc.retriable
                else "deterministic"
            )
            self._observe("failure_class", classification)
            delay = min(
                self._retry_max,
                self._retry_base * (2 ** max(0, message.attempts - 1)),
            )
            await self._release_claim_safely(
                message,
                available_at=datetime.now(UTC) + timedelta(seconds=delay),
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
            return False
        finally:
            self._in_flight = max(0, self._in_flight - 1)
            self._update_gauges()

    async def _release_claim_safely(
        self,
        message: OutboxMessage,
        *,
        available_at: datetime,
        error_code: str,
    ) -> None:
        try:
            await self._repository.release_claim(
                message.outbox_id,
                self._worker_id,
                available_at,
                error_code=error_code,
            )
        except Exception as exc:
            self._observe("delivery", "claim_release_failed")
            logger.warning(
                "Outbox claim release failed outbox_id=%s error=%s",
                message.outbox_id,
                type(exc).__name__,
            )

    def _observe(self, operation: str, outcome: str, count: int = 1) -> None:
        if self._metrics is not None and count > 0:
            self._metrics.observe_outbox(operation, outcome, count)

    def _observe_latency(
        self,
        stage: str,
        started_at: datetime,
        completed_at: datetime,
    ) -> None:
        if self._metrics is None:
            return
        observer = getattr(self._metrics, "observe_outbox_latency", None)
        if observer is not None:
            observer(stage, max(0.0, (completed_at - started_at).total_seconds()))

    def _observe_duration(self, stage: str, duration_seconds: float) -> None:
        if self._metrics is None:
            return
        observer = getattr(self._metrics, "observe_outbox_latency", None)
        if observer is not None:
            observer(stage, max(0.0, duration_seconds))

    def _update_gauges(self) -> None:
        if self._metrics is None:
            return
        setter = getattr(self._metrics, "set_outbox_gauge", None)
        if setter is not None:
            setter("publisher_in_flight", self._in_flight)
