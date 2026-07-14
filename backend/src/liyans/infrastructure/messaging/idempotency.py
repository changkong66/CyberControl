from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from liyans.core.errors import ErrorCode, MessageConflictError


class IdempotencyState(StrEnum):
    BUFFERED = "BUFFERED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"


class ReservationDecision(StrEnum):
    RESERVED = "RESERVED"
    DUPLICATE_BUFFERED = "DUPLICATE_BUFFERED"
    DUPLICATE_PROCESSING = "DUPLICATE_PROCESSING"
    DUPLICATE_COMPLETED = "DUPLICATE_COMPLETED"


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    key: str
    digest: str
    state: IdempotencyState


class IdempotencyStore(Protocol):
    async def reserve(self, key: str, digest: str) -> ReservationDecision: ...

    async def mark_processing(self, key: str, digest: str) -> None: ...

    async def complete(self, key: str, digest: str) -> None: ...

    async def abort(self, key: str, digest: str) -> None: ...


class InMemoryIdempotencyStore:
    """Executable baseline; production uses the PostgreSQL unique-key adapter."""

    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}
        self._lock = asyncio.Lock()

    async def reserve(self, key: str, digest: str) -> ReservationDecision:
        async with self._lock:
            existing = self._records.get(key)
            if existing is None:
                self._records[key] = IdempotencyRecord(
                    key=key,
                    digest=digest,
                    state=IdempotencyState.BUFFERED,
                )
                return ReservationDecision.RESERVED
            self._assert_digest(existing, digest)
            return ReservationDecision(f"DUPLICATE_{existing.state.value}")

    async def mark_processing(self, key: str, digest: str) -> None:
        await self._transition(key, digest, IdempotencyState.PROCESSING)

    async def complete(self, key: str, digest: str) -> None:
        await self._transition(key, digest, IdempotencyState.COMPLETED)

    async def abort(self, key: str, digest: str) -> None:
        async with self._lock:
            existing = self._records.get(key)
            if existing is None:
                return
            self._assert_digest(existing, digest)
            if existing.state != IdempotencyState.COMPLETED:
                del self._records[key]

    async def get(self, key: str) -> IdempotencyRecord | None:
        async with self._lock:
            return self._records.get(key)

    async def _transition(
        self,
        key: str,
        digest: str,
        state: IdempotencyState,
    ) -> None:
        async with self._lock:
            existing = self._records.get(key)
            if existing is None:
                raise RuntimeError("idempotency reservation is missing")
            self._assert_digest(existing, digest)
            self._records[key] = IdempotencyRecord(key=key, digest=digest, state=state)

    @staticmethod
    def _assert_digest(existing: IdempotencyRecord, digest: str) -> None:
        if existing.digest != digest:
            raise MessageConflictError(
                ErrorCode.MESSAGE_DUPLICATE_CONFLICT,
                "The idempotency key was reused for different message content.",
            )
