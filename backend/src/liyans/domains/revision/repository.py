from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol
from uuid import UUID

from liyans_contracts.topic4_c8 import RevisionCycleV1, RevisionPatchV1, RevisionPlanV1
from sqlalchemy.ext.asyncio import AsyncSession


class RevisionRepository(Protocol):
    def candidate_lock(
        self,
        session: AsyncSession,
        tenant_id: str,
        candidate_id: UUID,
    ) -> AbstractAsyncContextManager[None]: ...

    async def find_completed_request(
        self,
        session: AsyncSession,
        tenant_id: str,
        revision_request_id: UUID,
    ) -> dict[str, Any] | None: ...

    async def append_cycle(
        self,
        session: AsyncSession,
        tenant_id: str,
        cycle: RevisionCycleV1,
        audit_event_id: UUID,
        document: dict[str, Any] | None = None,
    ) -> None: ...

    async def append_plan(
        self,
        session: AsyncSession,
        tenant_id: str,
        plan: RevisionPlanV1,
        revision_cycle_version: int,
        audit_event_id: UUID,
    ) -> None: ...

    async def append_patch(
        self,
        session: AsyncSession,
        tenant_id: str,
        patch: RevisionPatchV1,
        audit_event_id: UUID,
    ) -> None: ...
