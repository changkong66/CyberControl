from __future__ import annotations

from uuid import UUID

from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.topic3 import (
    AgentTaskState,
    CandidateV1,
    GenerationSessionState,
    SSEChunkV1,
    Topic3ExecutionBlueprintV1,
)
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import assert_tenant

from .entities import (
    AgentTaskRecord,
    BlueprintRecord,
    CandidateRecord,
    GenerationSessionRecord,
    ModelInvocationRecord,
    StreamChunkRecord,
)
from .models import (
    Topic3AgentTaskModel,
    Topic3ExecutionBlueprintModel,
    Topic3GeneratedCandidateModel,
    Topic3GenerationSessionModel,
    Topic3ModelInvocationModel,
    Topic3StreamChunkModel,
)


class PostgresTopic3Repository:
    async def append_generation_session(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: GenerationSessionRecord,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        session.add(
            Topic3GenerationSessionModel(
                session_snapshot_id=record.session_snapshot_id,
                tenant_id=tenant_id,
                generation_session_id=record.generation_session_id,
                session_version=record.session_version,
                parent_session_snapshot_id=record.parent_session_snapshot_id,
                learner_ref=record.learner_ref,
                course_id=record.course_id,
                topic1_graph_snapshot_id=record.topic1_graph_snapshot_id,
                topic1_graph_version=record.topic1_graph_version,
                topic2_profile_id=record.topic2_profile_id,
                topic2_profile_version=record.topic2_profile_version,
                topic2_path_snapshot_id=record.topic2_path_snapshot_id,
                topic2_path_version=record.topic2_path_version,
                personalization_policy_digest=record.personalization_policy_digest,
                requested_resources=[value.value for value in record.requested_resources],
                state=record.state.value,
                request_document=record.request_document,
                result_document=record.result_document,
                content_sha256=record.content_sha256,
                audit_event_id=audit_event_id,
                created_by_subject=record.created_by_subject,
                frozen_at=record.frozen_at,
            )
        )
        await session.flush()

    async def latest_generation_session(
        self,
        session: AsyncSession,
        tenant_id: str,
        generation_session_id: UUID,
    ) -> GenerationSessionRecord | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic3GenerationSessionModel)
            .where(
                Topic3GenerationSessionModel.tenant_id == tenant_id,
                Topic3GenerationSessionModel.generation_session_id == generation_session_id,
            )
            .order_by(Topic3GenerationSessionModel.session_version.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return None if row is None else self._session(row)

    async def get_generation_session(
        self,
        session: AsyncSession,
        tenant_id: str,
        generation_session_id: UUID,
        session_version: int,
    ) -> GenerationSessionRecord | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic3GenerationSessionModel).where(
                Topic3GenerationSessionModel.tenant_id == tenant_id,
                Topic3GenerationSessionModel.generation_session_id == generation_session_id,
                Topic3GenerationSessionModel.session_version == session_version,
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else self._session(row)

    async def list_generation_sessions(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
        *,
        limit: int,
    ) -> list[GenerationSessionRecord]:
        assert_tenant(tenant_id)
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between one and 1000")
        latest_versions = (
            select(
                Topic3GenerationSessionModel.generation_session_id,
                func.max(Topic3GenerationSessionModel.session_version).label("latest_version"),
            )
            .where(
                Topic3GenerationSessionModel.tenant_id == tenant_id,
                Topic3GenerationSessionModel.learner_ref == learner_ref,
                Topic3GenerationSessionModel.course_id == course_id,
            )
            .group_by(Topic3GenerationSessionModel.generation_session_id)
            .subquery()
        )
        result = await session.execute(
            select(Topic3GenerationSessionModel)
            .join(
                latest_versions,
                and_(
                    latest_versions.c.generation_session_id
                    == Topic3GenerationSessionModel.generation_session_id,
                    latest_versions.c.latest_version
                    == Topic3GenerationSessionModel.session_version,
                ),
            )
            .where(Topic3GenerationSessionModel.tenant_id == tenant_id)
            .order_by(Topic3GenerationSessionModel.created_at.desc())
            .limit(limit)
        )
        return [self._session(row) for row in result.scalars()]

    async def append_blueprint(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: BlueprintRecord,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        blueprint = record.blueprint
        document = blueprint.model_dump(mode="json")
        session.add(
            Topic3ExecutionBlueprintModel(
                blueprint_snapshot_id=record.blueprint_snapshot_id,
                tenant_id=tenant_id,
                blueprint_id=blueprint.blueprint_id,
                blueprint_version=blueprint.blueprint_version,
                generation_session_id=blueprint.generation_session_id,
                generation_session_version=blueprint.generation_session_version,
                personalization_policy_digest=blueprint.personalization_policy_digest,
                max_parallelism=blueprint.max_parallelism,
                step_count=len(blueprint.steps),
                activation_document=record.activation_document,
                steps_document=[step.model_dump(mode="json") for step in blueprint.steps],
                blueprint_document=document,
                blueprint_sha256=blueprint.blueprint_sha256,
                audit_event_id=audit_event_id,
                created_by_subject=record.created_by_subject,
                frozen_at=record.frozen_at,
            )
        )
        await session.flush()

    async def get_blueprint(
        self,
        session: AsyncSession,
        tenant_id: str,
        blueprint_id: UUID,
        blueprint_version: str,
    ) -> BlueprintRecord | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic3ExecutionBlueprintModel).where(
                Topic3ExecutionBlueprintModel.tenant_id == tenant_id,
                Topic3ExecutionBlueprintModel.blueprint_id == blueprint_id,
                Topic3ExecutionBlueprintModel.blueprint_version == blueprint_version,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return BlueprintRecord(
            blueprint_snapshot_id=row.blueprint_snapshot_id,
            blueprint=Topic3ExecutionBlueprintV1.model_validate(row.blueprint_document),
            activation_document=dict(row.activation_document),
            created_by_subject=row.created_by_subject,
            frozen_at=row.frozen_at,
        )

    async def append_task(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: AgentTaskRecord,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        session.add(
            Topic3AgentTaskModel(
                task_record_id=record.task_record_id,
                tenant_id=tenant_id,
                task_id=record.task_id,
                task_version=record.task_version,
                blueprint_id=record.blueprint_id,
                blueprint_version=record.blueprint_version,
                agent=record.agent.value,
                resource_type=record.resource_type.value,
                state=record.state.value,
                dependency_task_ids=[str(value) for value in record.dependency_task_ids],
                attempt=record.attempt,
                max_attempts=record.max_attempts,
                timeout_seconds=record.timeout_seconds,
                request_document=record.request_document,
                result_document=record.result_document,
                error_document=record.error_document,
                request_sha256=record.request_sha256,
                result_sha256=record.result_sha256,
                started_at=record.started_at,
                completed_at=record.completed_at,
                audit_event_id=audit_event_id,
            )
        )
        await session.flush()

    async def latest_tasks(
        self,
        session: AsyncSession,
        tenant_id: str,
        blueprint_id: UUID,
        blueprint_version: str,
    ) -> list[AgentTaskRecord]:
        assert_tenant(tenant_id)
        latest_versions = (
            select(
                Topic3AgentTaskModel.task_id,
                func.max(Topic3AgentTaskModel.task_version).label("latest_version"),
            )
            .where(
                Topic3AgentTaskModel.tenant_id == tenant_id,
                Topic3AgentTaskModel.blueprint_id == blueprint_id,
                Topic3AgentTaskModel.blueprint_version == blueprint_version,
            )
            .group_by(Topic3AgentTaskModel.task_id)
            .subquery()
        )
        result = await session.execute(
            select(Topic3AgentTaskModel)
            .join(
                latest_versions,
                and_(
                    latest_versions.c.task_id == Topic3AgentTaskModel.task_id,
                    latest_versions.c.latest_version == Topic3AgentTaskModel.task_version,
                ),
            )
            .where(Topic3AgentTaskModel.tenant_id == tenant_id)
            .order_by(Topic3AgentTaskModel.created_at, Topic3AgentTaskModel.task_id)
        )
        return [self._task(row) for row in result.scalars()]

    async def append_candidate(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: CandidateRecord,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        candidate = record.candidate
        session.add(
            Topic3GeneratedCandidateModel(
                candidate_record_id=record.candidate_record_id,
                tenant_id=tenant_id,
                candidate_id=candidate.candidate_id,
                candidate_version=candidate.candidate_version,
                blueprint_id=candidate.blueprint_id,
                blueprint_version=candidate.blueprint_version,
                agent=candidate.provenance.agent.value,
                resource_type=candidate.resource_type.value,
                state=candidate.status.value,
                candidate_document=candidate.model_dump(mode="json"),
                candidate_sha256=candidate.candidate_sha256,
                personalization_policy_digest=candidate.personalization_policy_digest,
                audit_event_id=audit_event_id,
                frozen_at=record.frozen_at,
            )
        )
        await session.flush()

    async def list_candidates(
        self,
        session: AsyncSession,
        tenant_id: str,
        blueprint_id: UUID,
        blueprint_version: str,
    ) -> list[CandidateRecord]:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic3GeneratedCandidateModel)
            .where(
                Topic3GeneratedCandidateModel.tenant_id == tenant_id,
                Topic3GeneratedCandidateModel.blueprint_id == blueprint_id,
                Topic3GeneratedCandidateModel.blueprint_version == blueprint_version,
            )
            .order_by(
                Topic3GeneratedCandidateModel.created_at,
                Topic3GeneratedCandidateModel.candidate_id,
                Topic3GeneratedCandidateModel.candidate_version,
            )
        )
        return [self._candidate(row) for row in result.scalars()]

    async def get_candidate(
        self,
        session: AsyncSession,
        tenant_id: str,
        candidate_id: UUID,
        candidate_version: int,
    ) -> CandidateRecord | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic3GeneratedCandidateModel).where(
                Topic3GeneratedCandidateModel.tenant_id == tenant_id,
                Topic3GeneratedCandidateModel.candidate_id == candidate_id,
                Topic3GeneratedCandidateModel.candidate_version == candidate_version,
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else self._candidate(row)

    async def append_invocation(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: ModelInvocationRecord,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        session.add(
            Topic3ModelInvocationModel(
                invocation_id=record.invocation_id,
                tenant_id=tenant_id,
                task_id=record.task_id,
                task_version=record.task_version,
                provider_alias=record.provider_alias,
                model_alias=record.model_alias,
                provider_request_id=record.provider_request_id,
                state=record.state,
                request_sha256=record.request_sha256,
                response_sha256=record.response_sha256,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                latency_ms=record.latency_ms,
                error_document=record.error_document,
                started_at=record.started_at,
                completed_at=record.completed_at,
                audit_event_id=audit_event_id,
            )
        )
        await session.flush()

    async def append_stream_chunks(
        self,
        session: AsyncSession,
        tenant_id: str,
        records: list[StreamChunkRecord],
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        for record in records:
            chunk = record.chunk
            session.add(
                Topic3StreamChunkModel(
                    stream_chunk_record_id=record.stream_chunk_record_id,
                    tenant_id=tenant_id,
                    stream_id=chunk.stream_id,
                    fragment_id=chunk.fragment_id,
                    candidate_id=chunk.candidate_id,
                    candidate_version=chunk.candidate_version,
                    block_id=chunk.block_id,
                    block_partition=chunk.block_id or "__candidate__",
                    fragment_type=chunk.fragment_type.value,
                    chunk_index=chunk.chunk_index,
                    is_final=chunk.is_final,
                    data_encoding=chunk.data_encoding,
                    data=chunk.data,
                    data_sha256=chunk.data_sha256,
                    emitted_at=chunk.emitted_at,
                    audit_event_id=audit_event_id,
                )
            )
        await session.flush()

    async def list_stream_chunks(
        self,
        session: AsyncSession,
        tenant_id: str,
        stream_id: UUID,
        *,
        after_index: int | None,
        limit: int,
    ) -> list[StreamChunkRecord]:
        assert_tenant(tenant_id)
        if not 1 <= limit <= 5000:
            raise ValueError("limit must be between one and 5000")
        statement = select(Topic3StreamChunkModel).where(
            Topic3StreamChunkModel.tenant_id == tenant_id,
            Topic3StreamChunkModel.stream_id == stream_id,
        )
        if after_index is not None:
            statement = statement.where(Topic3StreamChunkModel.chunk_index > after_index)
        result = await session.execute(
            statement.order_by(
                Topic3StreamChunkModel.block_partition,
                Topic3StreamChunkModel.chunk_index,
            ).limit(limit)
        )
        return [self._chunk(row) for row in result.scalars()]

    @staticmethod
    def _assert_write(session: AsyncSession, tenant_id: str) -> None:
        assert_tenant(tenant_id)
        if not session.in_transaction():
            raise LiyanError(
                ErrorCode.DATABASE_TRANSACTION_STATE,
                "Topic 3 persistence requires an active transaction.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )

    @staticmethod
    def _session(row: Topic3GenerationSessionModel) -> GenerationSessionRecord:
        return GenerationSessionRecord(
            session_snapshot_id=row.session_snapshot_id,
            generation_session_id=row.generation_session_id,
            session_version=row.session_version,
            parent_session_snapshot_id=row.parent_session_snapshot_id,
            learner_ref=row.learner_ref,
            course_id=row.course_id,
            topic1_graph_snapshot_id=row.topic1_graph_snapshot_id,
            topic1_graph_version=row.topic1_graph_version,
            topic2_profile_id=row.topic2_profile_id,
            topic2_profile_version=row.topic2_profile_version,
            topic2_path_snapshot_id=row.topic2_path_snapshot_id,
            topic2_path_version=row.topic2_path_version,
            personalization_policy_digest=row.personalization_policy_digest,
            requested_resources=tuple(ResourceType(value) for value in row.requested_resources),
            state=GenerationSessionState(row.state),
            request_document=dict(row.request_document),
            result_document=dict(row.result_document),
            content_sha256=row.content_sha256,
            created_by_subject=row.created_by_subject,
            frozen_at=row.frozen_at,
        )

    @staticmethod
    def _task(row: Topic3AgentTaskModel) -> AgentTaskRecord:
        return AgentTaskRecord(
            task_record_id=row.task_record_id,
            task_id=row.task_id,
            task_version=row.task_version,
            blueprint_id=row.blueprint_id,
            blueprint_version=row.blueprint_version,
            agent=SourceAgent(row.agent),
            resource_type=ResourceType(row.resource_type),
            state=AgentTaskState(row.state),
            dependency_task_ids=tuple(UUID(value) for value in row.dependency_task_ids),
            attempt=row.attempt,
            max_attempts=row.max_attempts,
            timeout_seconds=row.timeout_seconds,
            request_document=dict(row.request_document),
            result_document=dict(row.result_document),
            error_document=dict(row.error_document),
            request_sha256=row.request_sha256,
            result_sha256=row.result_sha256,
            started_at=row.started_at,
            completed_at=row.completed_at,
        )

    @staticmethod
    def _candidate(row: Topic3GeneratedCandidateModel) -> CandidateRecord:
        return CandidateRecord(
            candidate_record_id=row.candidate_record_id,
            candidate=CandidateV1.model_validate(row.candidate_document),
            frozen_at=row.frozen_at,
        )

    @staticmethod
    def _chunk(row: Topic3StreamChunkModel) -> StreamChunkRecord:
        return StreamChunkRecord(
            stream_chunk_record_id=row.stream_chunk_record_id,
            chunk=SSEChunkV1(
                schema_version="topic3.sse-chunk.v1",
                stream_id=row.stream_id,
                fragment_id=row.fragment_id,
                candidate_id=row.candidate_id,
                candidate_version=row.candidate_version,
                block_id=row.block_id,
                fragment_type=row.fragment_type,
                chunk_index=row.chunk_index,
                is_final=row.is_final,
                data_encoding=row.data_encoding,
                data=row.data,
                data_sha256=row.data_sha256,
                emitted_at=row.emitted_at,
            ),
        )
