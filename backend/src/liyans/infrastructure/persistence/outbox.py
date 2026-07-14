from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from liyans_contracts.envelope import Topic3EnvelopeV1
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    outbox_id: UUID
    tenant_id: str
    envelope: Topic3EnvelopeV1
    created_at: datetime
    available_at: datetime
    published_at: datetime | None
    attempts: int = 0
    max_attempts: int = 3


class OutboxRepository(Protocol):
    """Must share the business transaction used to persist the owning state change."""

    async def append(self, session: AsyncSession, message: OutboxMessage) -> None: ...

    async def claim_batch(self, worker_id: str, limit: int) -> list[OutboxMessage]: ...

    async def mark_published(
        self,
        outbox_id: UUID,
        worker_id: str,
        published_at: datetime,
    ) -> None: ...

    async def release_claim(
        self,
        outbox_id: UUID,
        worker_id: str,
        available_at: datetime,
        *,
        error_code: str | None = None,
    ) -> None: ...
