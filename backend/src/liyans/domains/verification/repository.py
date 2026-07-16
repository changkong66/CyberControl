from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .entities import VerificationRecord, VerificationStateRecord


class VerificationRepository(Protocol):
    async def append_verification(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: VerificationRecord,
        audit_event_id: UUID,
    ) -> None: ...

    async def get_verification(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> VerificationRecord | None: ...

    async def append_state(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: VerificationStateRecord,
        audit_event_id: UUID,
    ) -> None: ...

    async def latest_state(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> VerificationStateRecord | None: ...
