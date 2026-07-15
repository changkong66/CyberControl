from __future__ import annotations

from typing import Protocol
from uuid import UUID

from liyans_contracts.topic1 import (
    Topic1CourseV1,
    Topic1GoldenQuestionV1,
    Topic1GraphContentV1,
    Topic1GraphSnapshotV1,
    Topic1KnowledgePointV1,
    Topic1MisconceptionV1,
    Topic1PrerequisiteV1,
    Topic1TextbookMappingV1,
    Topic1TextbookSectionV1,
    Topic1TextbookV1,
)
from sqlalchemy.ext.asyncio import AsyncSession


class Topic1Repository(Protocol):
    async def list_courses(self, session: AsyncSession, tenant_id: str) -> list[Topic1CourseV1]: ...

    async def get_course(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> Topic1CourseV1 | None: ...

    async def put_course(
        self,
        session: AsyncSession,
        tenant_id: str,
        course: Topic1CourseV1,
        subject_ref: str,
    ) -> None: ...

    async def list_knowledge_points(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> list[Topic1KnowledgePointV1]: ...

    async def get_knowledge_point(
        self,
        session: AsyncSession,
        tenant_id: str,
        kp_id: str,
    ) -> Topic1KnowledgePointV1 | None: ...

    async def put_knowledge_point(
        self,
        session: AsyncSession,
        tenant_id: str,
        knowledge_point: Topic1KnowledgePointV1,
        subject_ref: str,
    ) -> None: ...

    async def delete_knowledge_point(
        self,
        session: AsyncSession,
        tenant_id: str,
        kp_id: str,
    ) -> bool: ...

    async def list_prerequisites(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> list[Topic1PrerequisiteV1]: ...

    async def put_prerequisite(
        self,
        session: AsyncSession,
        tenant_id: str,
        prerequisite: Topic1PrerequisiteV1,
        subject_ref: str,
    ) -> None: ...

    async def delete_prerequisite(
        self,
        session: AsyncSession,
        tenant_id: str,
        edge_id: str,
    ) -> bool: ...

    async def replace_graph_content(
        self,
        session: AsyncSession,
        tenant_id: str,
        content: Topic1GraphContentV1,
        subject_ref: str,
    ) -> None: ...

    async def load_graph_content(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> Topic1GraphContentV1 | None: ...

    async def append_snapshot(
        self,
        session: AsyncSession,
        tenant_id: str,
        snapshot: Topic1GraphSnapshotV1,
        audit_event_id: UUID,
    ) -> None: ...

    async def get_snapshot(
        self,
        session: AsyncSession,
        tenant_id: str,
        snapshot_id: UUID,
    ) -> Topic1GraphSnapshotV1 | None: ...

    async def list_snapshots(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> list[Topic1GraphSnapshotV1]: ...

    async def latest_snapshot(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> Topic1GraphSnapshotV1 | None: ...


Topic1SupportingEntity = (
    Topic1MisconceptionV1
    | Topic1TextbookV1
    | Topic1TextbookSectionV1
    | Topic1TextbookMappingV1
    | Topic1GoldenQuestionV1
)
