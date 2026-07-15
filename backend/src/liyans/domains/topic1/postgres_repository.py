from __future__ import annotations

from typing import Any, TypeVar
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
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Topic1CourseModel,
    Topic1GoldenQuestionModel,
    Topic1GraphSnapshotModel,
    Topic1KnowledgePointModel,
    Topic1MisconceptionModel,
    Topic1PrerequisiteModel,
    Topic1TextbookMappingModel,
    Topic1TextbookModel,
    Topic1TextbookSectionModel,
)

ModelT = TypeVar("ModelT")


class PostgresTopic1Repository:
    async def list_courses(self, session: AsyncSession, tenant_id: str) -> list[Topic1CourseV1]:
        result = await session.execute(
            select(Topic1CourseModel)
            .where(Topic1CourseModel.tenant_id == tenant_id)
            .order_by(Topic1CourseModel.course_code)
        )
        return [self._course(row) for row in result.scalars()]

    async def get_course(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> Topic1CourseV1 | None:
        row = await session.get(Topic1CourseModel, (tenant_id, course_id))
        return None if row is None else self._course(row)

    async def put_course(
        self,
        session: AsyncSession,
        tenant_id: str,
        course: Topic1CourseV1,
        subject_ref: str,
    ) -> None:
        await session.merge(self._course_model(tenant_id, course, subject_ref))
        await session.flush()

    async def list_knowledge_points(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> list[Topic1KnowledgePointV1]:
        result = await session.execute(
            select(Topic1KnowledgePointModel)
            .where(
                Topic1KnowledgePointModel.tenant_id == tenant_id,
                Topic1KnowledgePointModel.course_id == course_id,
            )
            .order_by(
                Topic1KnowledgePointModel.topology_level,
                Topic1KnowledgePointModel.kp_id,
            )
        )
        return [self._knowledge_point(row) for row in result.scalars()]

    async def get_knowledge_point(
        self,
        session: AsyncSession,
        tenant_id: str,
        kp_id: str,
    ) -> Topic1KnowledgePointV1 | None:
        row = await session.get(Topic1KnowledgePointModel, (tenant_id, kp_id))
        return None if row is None else self._knowledge_point(row)

    async def put_knowledge_point(
        self,
        session: AsyncSession,
        tenant_id: str,
        knowledge_point: Topic1KnowledgePointV1,
        subject_ref: str,
    ) -> None:
        await session.merge(self._knowledge_point_model(tenant_id, knowledge_point, subject_ref))
        await session.flush()

    async def delete_knowledge_point(
        self,
        session: AsyncSession,
        tenant_id: str,
        kp_id: str,
    ) -> bool:
        result = await session.execute(
            delete(Topic1KnowledgePointModel).where(
                Topic1KnowledgePointModel.tenant_id == tenant_id,
                Topic1KnowledgePointModel.kp_id == kp_id,
            )
        )
        await session.flush()
        return result.rowcount == 1

    async def list_prerequisites(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> list[Topic1PrerequisiteV1]:
        result = await session.execute(
            select(Topic1PrerequisiteModel)
            .where(
                Topic1PrerequisiteModel.tenant_id == tenant_id,
                Topic1PrerequisiteModel.course_id == course_id,
            )
            .order_by(
                Topic1PrerequisiteModel.prerequisite_kp_id,
                Topic1PrerequisiteModel.dependent_kp_id,
            )
        )
        return [self._prerequisite(row) for row in result.scalars()]

    async def put_prerequisite(
        self,
        session: AsyncSession,
        tenant_id: str,
        prerequisite: Topic1PrerequisiteV1,
        subject_ref: str,
    ) -> None:
        await session.merge(self._prerequisite_model(tenant_id, prerequisite, subject_ref))
        await session.flush()

    async def delete_prerequisite(
        self,
        session: AsyncSession,
        tenant_id: str,
        edge_id: str,
    ) -> bool:
        result = await session.execute(
            delete(Topic1PrerequisiteModel).where(
                Topic1PrerequisiteModel.tenant_id == tenant_id,
                Topic1PrerequisiteModel.edge_id == edge_id,
            )
        )
        await session.flush()
        return result.rowcount == 1

    async def replace_graph_content(
        self,
        session: AsyncSession,
        tenant_id: str,
        content: Topic1GraphContentV1,
        subject_ref: str,
    ) -> None:
        await self.put_course(session, tenant_id, content.course, subject_ref)
        await session.execute(
            delete(Topic1KnowledgePointModel).where(
                Topic1KnowledgePointModel.tenant_id == tenant_id,
                Topic1KnowledgePointModel.course_id == content.course.course_id,
            )
        )
        await session.flush()
        for knowledge_point in content.knowledge_points:
            session.add(self._knowledge_point_model(tenant_id, knowledge_point, subject_ref))
        await session.flush()
        for textbook in content.textbooks:
            await session.merge(self._textbook_model(tenant_id, textbook, subject_ref))
        await session.flush()
        for section in self._ordered_sections(content.textbook_sections):
            await session.merge(self._section_model(tenant_id, section, subject_ref))
            await session.flush()
        session.add_all(
            [
                self._prerequisite_model(tenant_id, item, subject_ref)
                for item in content.prerequisites
            ]
        )
        session.add_all(
            [
                self._misconception_model(tenant_id, item, subject_ref)
                for item in content.misconceptions
            ]
        )
        session.add_all(
            [
                self._mapping_model(tenant_id, item, subject_ref)
                for item in content.textbook_mappings
            ]
        )
        session.add_all(
            [
                self._question_model(tenant_id, item, subject_ref)
                for item in content.golden_questions
            ]
        )
        await session.flush()

    async def load_graph_content(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> Topic1GraphContentV1 | None:
        course = await self.get_course(session, tenant_id, course_id)
        if course is None:
            return None
        knowledge_points = await self.list_knowledge_points(session, tenant_id, course_id)
        prerequisites = await self.list_prerequisites(session, tenant_id, course_id)
        kp_ids = [item.kp_id for item in knowledge_points]
        misconceptions = await self._scalars_for_ids(
            session,
            Topic1MisconceptionModel,
            Topic1MisconceptionModel.tenant_id == tenant_id,
            Topic1MisconceptionModel.kp_id.in_(kp_ids),
        )
        mappings = await self._scalars_for_ids(
            session,
            Topic1TextbookMappingModel,
            Topic1TextbookMappingModel.tenant_id == tenant_id,
            Topic1TextbookMappingModel.kp_id.in_(kp_ids),
        )
        section_ids = [item.section_id for item in mappings]
        sections = await self._load_sections_with_ancestors(session, tenant_id, section_ids)
        textbook_ids = [item.textbook_id for item in sections]
        textbooks = await self._scalars_for_ids(
            session,
            Topic1TextbookModel,
            Topic1TextbookModel.tenant_id == tenant_id,
            Topic1TextbookModel.textbook_id.in_(textbook_ids),
        )
        questions = await self._scalars_for_ids(
            session,
            Topic1GoldenQuestionModel,
            Topic1GoldenQuestionModel.tenant_id == tenant_id,
            Topic1GoldenQuestionModel.primary_kp_id.in_(kp_ids),
        )
        return Topic1GraphContentV1(
            course=course,
            knowledge_points=knowledge_points,
            prerequisites=prerequisites,
            misconceptions=sorted(
                (self._misconception(item) for item in misconceptions),
                key=lambda item: item.misconception_id,
            ),
            textbooks=sorted(
                (self._textbook(item) for item in textbooks),
                key=lambda item: item.textbook_id,
            ),
            textbook_sections=sorted(
                (self._section(item) for item in sections),
                key=lambda item: item.section_id,
            ),
            textbook_mappings=sorted(
                (self._mapping(item) for item in mappings),
                key=lambda item: item.mapping_id,
            ),
            golden_questions=sorted(
                (self._question(item) for item in questions),
                key=lambda item: item.question_id,
            ),
        )

    async def append_snapshot(
        self,
        session: AsyncSession,
        tenant_id: str,
        snapshot: Topic1GraphSnapshotV1,
        audit_event_id: UUID,
    ) -> None:
        session.add(
            Topic1GraphSnapshotModel(
                snapshot_id=snapshot.snapshot_id,
                tenant_id=tenant_id,
                course_id=snapshot.course_id,
                graph_version=snapshot.graph_version,
                parent_snapshot_id=snapshot.parent_snapshot_id,
                restored_from_snapshot_id=snapshot.restored_from_snapshot_id,
                snapshot_document=snapshot.model_dump(mode="json"),
                content_sha256=snapshot.content_sha256,
                node_count=snapshot.node_count,
                edge_count=snapshot.edge_count,
                audit_event_id=audit_event_id,
                created_by_subject=snapshot.created_by_subject,
                frozen_at=snapshot.frozen_at,
            )
        )
        await session.flush()

    async def get_snapshot(
        self,
        session: AsyncSession,
        tenant_id: str,
        snapshot_id: UUID,
    ) -> Topic1GraphSnapshotV1 | None:
        result = await session.execute(
            select(Topic1GraphSnapshotModel).where(
                Topic1GraphSnapshotModel.tenant_id == tenant_id,
                Topic1GraphSnapshotModel.snapshot_id == snapshot_id,
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else Topic1GraphSnapshotV1.model_validate(row.snapshot_document)

    async def list_snapshots(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> list[Topic1GraphSnapshotV1]:
        result = await session.execute(
            select(Topic1GraphSnapshotModel)
            .where(
                Topic1GraphSnapshotModel.tenant_id == tenant_id,
                Topic1GraphSnapshotModel.course_id == course_id,
            )
            .order_by(Topic1GraphSnapshotModel.graph_version.desc())
        )
        return [
            Topic1GraphSnapshotV1.model_validate(row.snapshot_document) for row in result.scalars()
        ]

    async def latest_snapshot(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> Topic1GraphSnapshotV1 | None:
        result = await session.execute(
            select(Topic1GraphSnapshotModel)
            .where(
                Topic1GraphSnapshotModel.tenant_id == tenant_id,
                Topic1GraphSnapshotModel.course_id == course_id,
            )
            .order_by(Topic1GraphSnapshotModel.graph_version.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return Topic1GraphSnapshotV1.model_validate(row.snapshot_document)

    @staticmethod
    async def _scalars_for_ids(
        session: AsyncSession,
        model: type[ModelT],
        *conditions: Any,
    ) -> list[ModelT]:
        result = await session.execute(select(model).where(*conditions))
        return list(result.scalars())

    async def _load_sections_with_ancestors(
        self,
        session: AsyncSession,
        tenant_id: str,
        section_ids: list[str],
    ) -> list[Topic1TextbookSectionModel]:
        loaded: dict[str, Topic1TextbookSectionModel] = {}
        pending = set(section_ids)
        while pending:
            rows = await self._scalars_for_ids(
                session,
                Topic1TextbookSectionModel,
                Topic1TextbookSectionModel.tenant_id == tenant_id,
                Topic1TextbookSectionModel.section_id.in_(pending),
            )
            for row in rows:
                loaded[row.section_id] = row
            pending = {
                row.parent_section_id
                for row in rows
                if row.parent_section_id is not None and row.parent_section_id not in loaded
            }
        return sorted(loaded.values(), key=lambda item: item.section_id)

    @staticmethod
    def _ordered_sections(
        sections: list[Topic1TextbookSectionV1],
    ) -> list[Topic1TextbookSectionV1]:
        pending = {item.section_id: item for item in sections}
        ordered: list[Topic1TextbookSectionV1] = []
        emitted: set[str] = set()
        while pending:
            ready = sorted(
                (
                    item
                    for item in pending.values()
                    if item.parent_section_id is None or item.parent_section_id in emitted
                ),
                key=lambda item: item.section_id,
            )
            if not ready:
                raise ValueError("textbook section hierarchy contains a cycle or missing parent")
            for item in ready:
                ordered.append(item)
                emitted.add(item.section_id)
                pending.pop(item.section_id)
        return ordered

    @staticmethod
    def _course(row: Topic1CourseModel) -> Topic1CourseV1:
        return Topic1CourseV1(
            course_id=row.course_id,
            revision=row.revision,
            course_code=row.course_code,
            title=row.title,
            description=row.description,
            locale=row.locale,
            academic_level=row.academic_level,
            credit_hours=row.credit_hours,
            status=row.status,
            authority_sources=row.authority_sources,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _course_model(
        tenant_id: str,
        value: Topic1CourseV1,
        subject_ref: str,
    ) -> Topic1CourseModel:
        return Topic1CourseModel(
            tenant_id=tenant_id,
            course_id=value.course_id,
            revision=value.revision,
            course_code=value.course_code,
            title=value.title,
            description=value.description,
            locale=value.locale,
            academic_level=value.academic_level,
            credit_hours=value.credit_hours,
            status=value.status.value,
            authority_sources=[item.model_dump(mode="json") for item in value.authority_sources],
            created_by_subject=subject_ref,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )

    @staticmethod
    def _knowledge_point(row: Topic1KnowledgePointModel) -> Topic1KnowledgePointV1:
        return Topic1KnowledgePointV1(
            kp_id=row.kp_id,
            course_id=row.course_id,
            revision=row.revision,
            title=row.title,
            aliases=row.aliases,
            summary=row.summary,
            learning_objectives=row.learning_objectives,
            category=row.category,
            difficulty_level=row.difficulty_level,
            difficulty_score=row.difficulty_score,
            topology_level=row.topology_level,
            topology_weight=row.topology_weight,
            estimated_minutes=row.estimated_minutes,
            formula_signatures=row.formula_signatures,
            tags=row.tags,
            status=row.status,
            authority_sources=row.authority_sources,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _knowledge_point_model(
        tenant_id: str,
        value: Topic1KnowledgePointV1,
        subject_ref: str,
    ) -> Topic1KnowledgePointModel:
        return Topic1KnowledgePointModel(
            tenant_id=tenant_id,
            kp_id=value.kp_id,
            course_id=value.course_id,
            revision=value.revision,
            title=value.title,
            aliases=value.aliases,
            summary=value.summary,
            learning_objectives=value.learning_objectives,
            category=value.category,
            difficulty_level=value.difficulty_level,
            difficulty_score=value.difficulty_score,
            topology_level=value.topology_level,
            topology_weight=value.topology_weight,
            estimated_minutes=value.estimated_minutes,
            formula_signatures=value.formula_signatures,
            tags=value.tags,
            status=value.status.value,
            authority_sources=[item.model_dump(mode="json") for item in value.authority_sources],
            created_by_subject=subject_ref,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )

    @staticmethod
    def _prerequisite(row: Topic1PrerequisiteModel) -> Topic1PrerequisiteV1:
        return Topic1PrerequisiteV1(
            edge_id=row.edge_id,
            course_id=row.course_id,
            prerequisite_kp_id=row.prerequisite_kp_id,
            dependent_kp_id=row.dependent_kp_id,
            relation_type=row.relation_type,
            strength=row.strength,
            rationale=row.rationale,
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _prerequisite_model(
        tenant_id: str,
        value: Topic1PrerequisiteV1,
        subject_ref: str,
    ) -> Topic1PrerequisiteModel:
        return Topic1PrerequisiteModel(
            tenant_id=tenant_id,
            edge_id=value.edge_id,
            course_id=value.course_id,
            prerequisite_kp_id=value.prerequisite_kp_id,
            dependent_kp_id=value.dependent_kp_id,
            relation_type=value.relation_type.value,
            strength=value.strength,
            rationale=value.rationale,
            revision=value.revision,
            created_by_subject=subject_ref,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )

    @staticmethod
    def _misconception(row: Topic1MisconceptionModel) -> Topic1MisconceptionV1:
        return Topic1MisconceptionV1(
            misconception_id=row.misconception_id,
            kp_id=row.kp_id,
            title=row.title,
            description=row.description,
            trigger_pattern=row.trigger_pattern,
            diagnosis_tags=row.diagnosis_tags,
            remediation_hint=row.remediation_hint,
            severity=row.severity,
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _misconception_model(
        tenant_id: str,
        value: Topic1MisconceptionV1,
        subject_ref: str,
    ) -> Topic1MisconceptionModel:
        return Topic1MisconceptionModel(
            tenant_id=tenant_id,
            misconception_id=value.misconception_id,
            kp_id=value.kp_id,
            title=value.title,
            description=value.description,
            trigger_pattern=value.trigger_pattern,
            diagnosis_tags=value.diagnosis_tags,
            remediation_hint=value.remediation_hint,
            severity=value.severity.value,
            revision=value.revision,
            created_by_subject=subject_ref,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )

    @staticmethod
    def _textbook(row: Topic1TextbookModel) -> Topic1TextbookV1:
        return Topic1TextbookV1(
            textbook_id=row.textbook_id,
            title=row.title,
            authors=row.authors,
            publisher=row.publisher,
            edition=row.edition,
            isbn=row.isbn,
            publication_year=row.publication_year,
            authority_level=row.authority_level,
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _textbook_model(
        tenant_id: str,
        value: Topic1TextbookV1,
        subject_ref: str,
    ) -> Topic1TextbookModel:
        return Topic1TextbookModel(
            tenant_id=tenant_id,
            textbook_id=value.textbook_id,
            title=value.title,
            authors=value.authors,
            publisher=value.publisher,
            edition=value.edition,
            isbn=value.isbn,
            publication_year=value.publication_year,
            authority_level=value.authority_level,
            revision=value.revision,
            created_by_subject=subject_ref,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )

    @staticmethod
    def _section(row: Topic1TextbookSectionModel) -> Topic1TextbookSectionV1:
        return Topic1TextbookSectionV1(
            section_id=row.section_id,
            textbook_id=row.textbook_id,
            parent_section_id=row.parent_section_id,
            chapter_number=row.chapter_number,
            title=row.title,
            start_page=row.start_page,
            end_page=row.end_page,
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _section_model(
        tenant_id: str,
        value: Topic1TextbookSectionV1,
        subject_ref: str,
    ) -> Topic1TextbookSectionModel:
        return Topic1TextbookSectionModel(
            tenant_id=tenant_id,
            section_id=value.section_id,
            textbook_id=value.textbook_id,
            parent_section_id=value.parent_section_id,
            chapter_number=value.chapter_number,
            title=value.title,
            start_page=value.start_page,
            end_page=value.end_page,
            revision=value.revision,
            created_by_subject=subject_ref,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )

    @staticmethod
    def _mapping(row: Topic1TextbookMappingModel) -> Topic1TextbookMappingV1:
        return Topic1TextbookMappingV1(
            mapping_id=row.mapping_id,
            kp_id=row.kp_id,
            section_id=row.section_id,
            mapping_type=row.mapping_type,
            coverage=row.coverage,
            note=row.note,
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _mapping_model(
        tenant_id: str,
        value: Topic1TextbookMappingV1,
        subject_ref: str,
    ) -> Topic1TextbookMappingModel:
        return Topic1TextbookMappingModel(
            tenant_id=tenant_id,
            mapping_id=value.mapping_id,
            kp_id=value.kp_id,
            section_id=value.section_id,
            mapping_type=value.mapping_type.value,
            coverage=value.coverage,
            note=value.note,
            revision=value.revision,
            created_by_subject=subject_ref,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )

    @staticmethod
    def _question(row: Topic1GoldenQuestionModel) -> Topic1GoldenQuestionV1:
        return Topic1GoldenQuestionV1(
            question_id=row.question_id,
            primary_kp_id=row.primary_kp_id,
            related_kp_ids=row.related_kp_ids,
            question_type=row.question_type,
            stem_markdown=row.stem_markdown,
            answer_document=row.answer_document,
            solution_markdown=row.solution_markdown,
            difficulty_level=row.difficulty_level,
            discrimination=row.discrimination,
            diagnostic_tags=row.diagnostic_tags,
            misconception_ids=row.misconception_ids,
            authority_sources=row.authority_sources,
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _question_model(
        tenant_id: str,
        value: Topic1GoldenQuestionV1,
        subject_ref: str,
    ) -> Topic1GoldenQuestionModel:
        return Topic1GoldenQuestionModel(
            tenant_id=tenant_id,
            question_id=value.question_id,
            primary_kp_id=value.primary_kp_id,
            related_kp_ids=value.related_kp_ids,
            question_type=value.question_type.value,
            stem_markdown=value.stem_markdown,
            answer_document=value.answer_document,
            solution_markdown=value.solution_markdown,
            difficulty_level=value.difficulty_level,
            discrimination=value.discrimination,
            diagnostic_tags=value.diagnostic_tags,
            misconception_ids=value.misconception_ids,
            authority_sources=[item.model_dump(mode="json") for item in value.authority_sources],
            revision=value.revision,
            created_by_subject=subject_ref,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )
