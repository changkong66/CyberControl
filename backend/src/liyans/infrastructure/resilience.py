from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from random import SystemRandom
from time import monotonic
from typing import TypeVar

from liyans.core.errors import CircuitOpenError, OperationTimeoutError, RateLimitExceeded

T = TypeVar("T")
SYSTEM_RANDOM = SystemRandom()


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.2
    max_delay_seconds: float = 5.0
    jitter_seconds: float = 0.1

    def delay_for(self, attempt: int) -> float:
        exponential = self.base_delay_seconds * (2 ** max(0, attempt - 1))
        return min(self.max_delay_seconds, exponential) + SYSTEM_RANDOM.uniform(
            0.0,
            self.jitter_seconds,
        )


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    retryable: Callable[[Exception], bool],
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await operation()
        except Exception as exc:
            last_error = exc
            if attempt >= policy.max_attempts or not retryable(exc):
                raise
            await asyncio.sleep(policy.delay_for(attempt))
    if last_error is None:
        raise RuntimeError("retry loop completed without a result or exception")
    raise last_error


async def run_with_timeout(
    operation_name: str,
    timeout_seconds: float,
    operation: Callable[[], Awaitable[T]],
) -> T:
    try:
        async with asyncio.timeout(timeout_seconds):
            return await operation()
    except TimeoutError as exc:
        raise OperationTimeoutError(operation_name) from exc


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        reset_timeout_seconds: float = 30.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._half_open_probe_in_flight = False
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    async def execute(self, operation: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if monotonic() - self._opened_at < self.reset_timeout_seconds:
                    raise CircuitOpenError(self.name)
                self._state = CircuitState.HALF_OPEN
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_probe_in_flight:
                    raise CircuitOpenError(self.name)
                self._half_open_probe_in_flight = True

        try:
            result = await operation()
        except Exception:
            async with self._lock:
                self._failures += 1
                self._half_open_probe_in_flight = False
                if (
                    self._state == CircuitState.HALF_OPEN
                    or self._failures >= self.failure_threshold
                ):
                    self._state = CircuitState.OPEN
                    self._opened_at = monotonic()
            raise

        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._half_open_probe_in_flight = False
        return result


class TokenBucketRateLimiter:
    def __init__(self, *, capacity: float, refill_rate_per_second: float) -> None:
        if capacity <= 0 or refill_rate_per_second <= 0:
            raise ValueError("capacity and refill_rate_per_second must be positive")
        self.capacity = capacity
        self.refill_rate_per_second = refill_rate_per_second
        self._tokens = capacity
        self._updated_at = monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        async with self._lock:
            now = monotonic()
            elapsed = now - self._updated_at
            self._tokens = min(
                self.capacity,
                self._tokens + elapsed * self.refill_rate_per_second,
            )
            self._updated_at = now
            if self._tokens >= tokens:
                self._tokens -= tokens
                return
            missing = tokens - self._tokens
            retry_after = missing / self.refill_rate_per_second
            raise RateLimitExceeded(retry_after)


class AsyncBulkhead:
    def __init__(self, concurrency: int) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least one")
        self._semaphore = asyncio.Semaphore(concurrency)

    async def execute(self, operation: Callable[[], Awaitable[T]]) -> T:
        async with self._semaphore:
            return await operation()
