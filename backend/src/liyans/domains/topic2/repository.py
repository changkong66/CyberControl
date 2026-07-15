from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .entities import (
    LearningBehaviorEventDraft,
    LearningBehaviorEventRecord,
    LearningPathRecord,
    LearningPathSnapshotDraft,
    MemoryStateDraft,
    MemoryStateRecord,
    PathChangeDraft,
    ProfileFeatureDraft,
    StudentProfileDraft,
    StudentProfileRecord,
)


class Topic2Repository(Protocol):
    async def append_behavior_event(
        self,
        session: AsyncSession,
        tenant_id: str,
        event: LearningBehaviorEventDraft,
        audit_event_id: UUID,
    ) -> LearningBehaviorEventRecord: ...

    async def list_behavior_events(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        received_after: datetime | None = None,
        received_after_event_id: UUID | None = None,
        limit: int = 1000,
    ) -> list[LearningBehaviorEventRecord]: ...

    async def list_review_events(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
        *,
        received_after: datetime | None = None,
        received_after_event_id: UUID | None = None,
        received_until: datetime | None = None,
        occurred_until: datetime | None = None,
        limit: int = 1000,
    ) -> list[LearningBehaviorEventRecord]: ...

    async def append_profile(
        self,
        session: AsyncSession,
        tenant_id: str,
        profile: StudentProfileDraft,
        audit_event_id: UUID,
        created_by_subject: str,
    ) -> StudentProfileRecord: ...

    async def latest_profile(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
    ) -> StudentProfileRecord | None: ...

    async def get_profile(
        self,
        session: AsyncSession,
        tenant_id: str,
        profile_id: UUID,
    ) -> StudentProfileRecord | None: ...

    async def list_profile_versions(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
        *,
        limit: int = 100,
    ) -> list[StudentProfileRecord]: ...

    async def list_profile_features(
        self,
        session: AsyncSession,
        tenant_id: str,
        profile_id: UUID,
    ) -> list[ProfileFeatureDraft]: ...

    async def append_memory_states(
        self,
        session: AsyncSession,
        tenant_id: str,
        states: Sequence[MemoryStateDraft],
        audit_event_id: UUID,
    ) -> list[MemoryStateRecord]: ...

    async def latest_memory_states(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
        *,
        kp_ids: Sequence[str] | None = None,
    ) -> list[MemoryStateRecord]: ...

    async def get_memory_states(
        self,
        session: AsyncSession,
        tenant_id: str,
        memory_state_ids: Sequence[UUID],
    ) -> list[MemoryStateRecord]: ...

    async def due_memory_states(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        due_at: datetime,
        limit: int,
    ) -> list[MemoryStateRecord]: ...

    async def append_learning_path(
        self,
        session: AsyncSession,
        tenant_id: str,
        snapshot: LearningPathSnapshotDraft,
        change: PathChangeDraft,
        audit_event_id: UUID,
        created_by_subject: str,
    ) -> LearningPathRecord: ...

    async def latest_learning_path(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
    ) -> LearningPathRecord | None: ...

    async def get_learning_path(
        self,
        session: AsyncSession,
        tenant_id: str,
        path_snapshot_id: UUID,
    ) -> LearningPathRecord | None: ...

    async def list_learning_paths(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
        *,
        limit: int = 100,
    ) -> list[LearningPathRecord]: ...
