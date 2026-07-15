from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .entities import (
    AgentTaskRecord,
    BlueprintRecord,
    CandidateRecord,
    GenerationSessionRecord,
    ModelInvocationRecord,
    StreamChunkRecord,
)


class Topic3Repository(Protocol):
    async def append_generation_session(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: GenerationSessionRecord,
        audit_event_id: UUID,
    ) -> None: ...

    async def latest_generation_session(
        self,
        session: AsyncSession,
        tenant_id: str,
        generation_session_id: UUID,
    ) -> GenerationSessionRecord | None: ...

    async def get_generation_session(
        self,
        session: AsyncSession,
        tenant_id: str,
        generation_session_id: UUID,
        session_version: int,
    ) -> GenerationSessionRecord | None: ...

    async def list_generation_sessions(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
        *,
        limit: int,
    ) -> list[GenerationSessionRecord]: ...

    async def append_blueprint(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: BlueprintRecord,
        audit_event_id: UUID,
    ) -> None: ...

    async def get_blueprint(
        self,
        session: AsyncSession,
        tenant_id: str,
        blueprint_id: UUID,
        blueprint_version: str,
    ) -> BlueprintRecord | None: ...

    async def append_task(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: AgentTaskRecord,
        audit_event_id: UUID,
    ) -> None: ...

    async def latest_tasks(
        self,
        session: AsyncSession,
        tenant_id: str,
        blueprint_id: UUID,
        blueprint_version: str,
    ) -> list[AgentTaskRecord]: ...

    async def append_candidate(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: CandidateRecord,
        audit_event_id: UUID,
    ) -> None: ...

    async def list_candidates(
        self,
        session: AsyncSession,
        tenant_id: str,
        blueprint_id: UUID,
        blueprint_version: str,
    ) -> list[CandidateRecord]: ...

    async def get_candidate(
        self,
        session: AsyncSession,
        tenant_id: str,
        candidate_id: UUID,
        candidate_version: int,
    ) -> CandidateRecord | None: ...

    async def append_invocation(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: ModelInvocationRecord,
        audit_event_id: UUID,
    ) -> None: ...

    async def append_stream_chunks(
        self,
        session: AsyncSession,
        tenant_id: str,
        records: list[StreamChunkRecord],
        audit_event_id: UUID,
    ) -> None: ...

    async def list_stream_chunks(
        self,
        session: AsyncSession,
        tenant_id: str,
        stream_id: UUID,
        *,
        after_index: int | None,
        limit: int,
    ) -> list[StreamChunkRecord]: ...
