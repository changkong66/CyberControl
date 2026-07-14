from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from itertools import count
from typing import Any
from uuid import UUID, uuid4

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.infrastructure.resilience import (
    AsyncBulkhead,
    CircuitBreaker,
    RetryPolicy,
    TokenBucketRateLimiter,
    retry_async,
    run_with_timeout,
)

logger = logging.getLogger(__name__)


class TaskPriority(IntEnum):
    CRITICAL = 0
    HIGH = 10
    NORMAL = 20
    LOW = 30


@dataclass(frozen=True, slots=True)
class TaskRequest:
    task_type: str
    tenant_id: str
    payload: dict[str, Any]
    priority: TaskPriority = TaskPriority.NORMAL
    task_id: UUID = field(default_factory=uuid4)
    timeout_seconds: float = 30.0
    max_attempts: int = 3
    expires_at: datetime | None = None
    correlation_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.task_type or not self.tenant_id:
            raise ValueError("task_type and tenant_id are required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 1 <= self.max_attempts <= 16:
            raise ValueError("max_attempts must be between one and sixteen")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: UUID
    succeeded: bool
    attempts: int
    output: dict[str, Any] | None
    error_code: str | None
    completed_at: datetime


TaskHandler = Callable[[TaskRequest], Awaitable[dict[str, Any]]]
CompensationHandler = Callable[[TaskRequest, Exception], Awaitable[None]]


@dataclass(order=True, slots=True)
class _QueueItem:
    priority: int
    ordinal: int
    request: TaskRequest = field(compare=False)
    future: asyncio.Future[TaskResult] = field(compare=False)


class AsyncTaskQueue:
    def __init__(
        self,
        *,
        worker_count: int = 4,
        queue_capacity: int = 1024,
        per_tenant_capacity: float = 20.0,
        per_tenant_refill_per_second: float = 10.0,
        task_concurrency: int = 16,
    ) -> None:
        if worker_count < 1 or queue_capacity < 1:
            raise ValueError("worker_count and queue_capacity must be positive")
        self._worker_count = worker_count
        self._queue: asyncio.PriorityQueue[_QueueItem] = asyncio.PriorityQueue(
            maxsize=queue_capacity
        )
        self._handlers: dict[str, TaskHandler] = {}
        self._compensators: dict[str, CompensationHandler] = {}
        self._breakers: dict[str, CircuitBreaker] = {}
        self._bulkhead = AsyncBulkhead(task_concurrency)
        self._tenant_limiters: dict[str, TokenBucketRateLimiter] = {}
        self._limiter_capacity = per_tenant_capacity
        self._limiter_refill = per_tenant_refill_per_second
        self._workers: list[asyncio.Task[None]] = []
        self._ordinal = count()
        self._closed = False
        self._dead_letters: list[TaskResult] = []

    @property
    def running(self) -> bool:
        return bool(self._workers) and not self._closed

    @property
    def dead_letters(self) -> tuple[TaskResult, ...]:
        return tuple(self._dead_letters)

    def register(
        self,
        task_type: str,
        handler: TaskHandler,
        *,
        compensation: CompensationHandler | None = None,
        circuit_failure_threshold: int = 5,
    ) -> None:
        if task_type in self._handlers:
            raise ValueError(f"task handler already registered: {task_type}")
        self._handlers[task_type] = handler
        if compensation is not None:
            self._compensators[task_type] = compensation
        self._breakers[task_type] = CircuitBreaker(
            task_type,
            failure_threshold=circuit_failure_threshold,
        )

    async def start(self) -> None:
        if self._workers:
            return
        self._closed = False
        self._workers = [
            asyncio.create_task(self._worker(index), name=f"task-worker-{index}")
            for index in range(self._worker_count)
        ]

    async def close(self) -> None:
        self._closed = True
        await self._queue.join()
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def enqueue(self, request: TaskRequest) -> asyncio.Future[TaskResult]:
        if self._closed:
            raise LiyanError(
                ErrorCode.TASK_QUEUE_CLOSED,
                "The task queue is closed.",
                category=ErrorCategory.TASK,
                status_code=503,
            )
        future: asyncio.Future[TaskResult] = asyncio.get_running_loop().create_future()
        item = _QueueItem(
            priority=int(request.priority),
            ordinal=next(self._ordinal),
            request=request,
            future=future,
        )
        await self._queue.put(item)
        return future

    async def submit(self, request: TaskRequest) -> TaskResult:
        future = await self.enqueue(request)
        return await future

    async def _worker(self, index: int) -> None:
        del index
        while True:
            item = await self._queue.get()
            try:
                result = await self._execute(item.request)
                if not item.future.cancelled():
                    item.future.set_result(result)
            except Exception as exc:
                result = await self._compensate(item.request, exc)
                self._dead_letters.append(result)
                if not item.future.cancelled():
                    item.future.set_result(result)
            finally:
                self._queue.task_done()

    async def _execute(self, request: TaskRequest) -> TaskResult:
        if request.expires_at is not None and request.expires_at <= datetime.now(UTC):
            raise LiyanError(
                ErrorCode.MESSAGE_EXPIRED,
                "The task expired before execution.",
                category=ErrorCategory.TASK,
                status_code=410,
            )
        try:
            handler = self._handlers[request.task_type]
            breaker = self._breakers[request.task_type]
        except KeyError as exc:
            raise LiyanError(
                ErrorCode.TASK_HANDLER_MISSING,
                "No task handler is registered for the task type.",
                category=ErrorCategory.TASK,
                status_code=422,
                details={"task_type": request.task_type},
            ) from exc

        limiter = self._tenant_limiters.setdefault(
            request.tenant_id,
            TokenBucketRateLimiter(
                capacity=self._limiter_capacity,
                refill_rate_per_second=self._limiter_refill,
            ),
        )
        attempts = 0

        async def operation() -> dict[str, Any]:
            nonlocal attempts
            attempts += 1
            await limiter.acquire()

            async def invoke() -> dict[str, Any]:
                return await run_with_timeout(
                    request.task_type,
                    request.timeout_seconds,
                    lambda: handler(request),
                )

            return await breaker.execute(lambda: self._bulkhead.execute(invoke))

        try:
            output = await retry_async(
                operation,
                policy=RetryPolicy(max_attempts=request.max_attempts),
                retryable=lambda exc: isinstance(exc, LiyanError) and exc.retriable,
            )
        except Exception as exc:
            exc.liyans_attempts = attempts
            raise
        return TaskResult(
            task_id=request.task_id,
            succeeded=True,
            attempts=attempts,
            output=output,
            error_code=None,
            completed_at=datetime.now(UTC),
        )

    async def _compensate(self, request: TaskRequest, exc: Exception) -> TaskResult:
        compensation = self._compensators.get(request.task_type)
        if compensation is not None:
            try:
                await compensation(request, exc)
            except Exception:
                logger.exception("Task compensation failed for task %s", request.task_id)
        error_code = exc.code.value if isinstance(exc, LiyanError) else ErrorCode.TASK_FAILED.value
        return TaskResult(
            task_id=request.task_id,
            succeeded=False,
            attempts=int(getattr(exc, "liyans_attempts", 0)),
            output=None,
            error_code=error_code,
            completed_at=datetime.now(UTC),
        )
