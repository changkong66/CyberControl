from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from liyans_contracts.envelope import Topic3EnvelopeV1


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    outbox_id: UUID
    tenant_id: str
    envelope: Topic3EnvelopeV1
    created_at: datetime
    available_at: datetime
    published_at: datetime | None


class OutboxRepository(Protocol):
    """Must share the business transaction used to persist the owning state change."""

    async def append(self, message: OutboxMessage) -> None: ...

    async def claim_batch(self, worker_id: str, limit: int) -> list[OutboxMessage]: ...

    async def mark_published(self, outbox_id: UUID, published_at: datetime) -> None: ...

    async def release_claim(self, outbox_id: UUID, available_at: datetime) -> None: ...
