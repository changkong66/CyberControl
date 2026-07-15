from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    MessageKind,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)
from liyans_contracts.topic1 import Topic1GraphSnapshotV1
from liyans_contracts.topic2 import Topic2AgentContextV1
from liyans_contracts.topic3 import (
    AgentTaskState,
    CandidateV1,
    GenerationSessionState,
    SSEChunkV1,
    Topic3AgentTaskSnapshotV1,
    Topic3ExecutionBlueprintV1,
    Topic3GenerationCommandV1,
    Topic3GenerationResultV1,
)
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError, MessageConflictError
from liyans.core.tenant import TenantContext, current_tenant
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.models import (
    AuditEventModel,
    IdempotencyRecordModel,
    IdempotencyStatus,
    OutboxMessageModel,
)
from liyans.infrastructure.database.session import (
    DatabaseSessionManager,
    TransactionIsolation,
    TransactionRetryPolicy,
)
from liyans.infrastructure.observability.audit import (
    GENESIS_HASH,
    AuditDraft,
    AuditRecord,
    build_audit_record,
)
from liyans.infrastructure.persistence.outbox import OutboxMessage
from liyans.infrastructure.persistence.postgres_outbox import PostgresOutboxRepository

from .blueprint import BlueprintDecision
from .entities import (
    AgentTaskRecord,
    BlueprintRecord,
    CandidateRecord,
    GenerationSessionRecord,
    ModelInvocationRecord,
    StreamChunkRecord,
)
from .postgres_repository import PostgresTopic3Repository

IDEMPOTENCY_RETENTION = timedelta(days=1)
OUTBOX_RETENTION = timedelta(days=1)

MutationCallback = Callable[[AsyncSession, TenantContext], Awaitable[dict[str, Any]]]


class Topic3Service:
    def __init__(
        self,
        database: DatabaseSessionManager,
        repository: PostgresTopic3Repository,
        outbox: PostgresOutboxRepository,
        *,
        instance_id: str,
    ) -> None:
        self._database = database
        self._repository = repository
        self._outbox = outbox
        self._instance_id = instance_id

    async def create_workflow(
        self,
        command: Topic3GenerationCommandV1,
        graph: Topic1GraphSnapshotV1,
        personalization: Topic2AgentContextV1,
        decision: BlueprintDecision,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        context = current_tenant()
        self._assert_learner_access(context, command.learner_ref)
        request_document = {
            "command": command.model_dump(mode="json"),
            "personalization": personalization.model_dump(mode="json"),
        }

        async def callback(session: AsyncSession, tenant: TenantContext) -> dict[str, Any]:
            await self._lock(
                session, f"workflow:{tenant.tenant_id}:{command.generation_session_id}"
            )
            existing = await self._repository.latest_generation_session(
                session,
                tenant.tenant_id,
                command.generation_session_id,
            )
            if existing is not None:
                raise self._conflict("The Topic 3 generation session already exists.")
            now = datetime.now(UTC)
            blueprint = decision.blueprint
            session_record = self._session_record(
                command=command,
                graph=graph,
                personalization=personalization,
                session_version=1,
                parent_session_snapshot_id=None,
                state=GenerationSessionState.PLANNED,
                request_document=request_document,
                result_document={
                    "blueprint_id": str(blueprint.blueprint_id),
                    "blueprint_version": blueprint.blueprint_version,
                    "candidate_ids": [],
                    "failed_agents": [],
                },
                subject_ref=tenant.subject_ref,
                frozen_at=now,
            )
            pending_tasks = [
                self._pending_task(step, blueprint, command, now) for step in blueprint.steps
            ]
            audit = await self._append_audit(
                session,
                tenant,
                action="GENERATION_WORKFLOW_CREATED",
                target_ref=str(command.generation_session_id),
                metadata={
                    "blueprint_id": str(blueprint.blueprint_id),
                    "blueprint_version": blueprint.blueprint_version,
                    "requested_resources": [value.value for value in command.requested_resources],
                },
            )
            await self._repository.append_generation_session(
                session,
                tenant.tenant_id,
                session_record,
                audit.event_id,
            )
            await self._repository.append_blueprint(
                session,
                tenant.tenant_id,
                BlueprintRecord(
                    blueprint_snapshot_id=uuid5(blueprint.blueprint_id, "snapshot-v1"),
                    blueprint=blueprint,
                    activation_document=decision.activation_document,
                    created_by_subject=tenant.subject_ref,
                    frozen_at=now,
                ),
                audit.event_id,
            )
            for task in pending_tasks:
                await self._repository.append_task(
                    session,
                    tenant.tenant_id,
                    task,
                    audit.event_id,
                )
            payload = {
                "generation_session_id": str(command.generation_session_id),
                "session_version": 1,
                "state": GenerationSessionState.PLANNED.value,
                "blueprint": blueprint.model_dump(mode="json"),
                "tasks": [self.task_document(task) for task in pending_tasks],
            }
            await self._append_outbox(
                session,
                tenant,
                event_type="topic3.workflow.created",
                payload=payload,
                partition_key=self._partition_key(
                    tenant.tenant_id,
                    command.generation_session_id,
                ),
            )
            return payload

        return await self._execute_mutation(
            operation="topic3.workflow.create",
            idempotency_key=idempotency_key,
            request_document=request_document,
            callback=callback,
        )

    async def start_workflow(self, generation_session_id: UUID) -> GenerationSessionRecord:
        started_at = datetime.now(UTC)

        async def callback(session: AsyncSession, tenant: TenantContext) -> dict[str, Any]:
            await self._lock(
                session,
                f"workflow:{tenant.tenant_id}:{generation_session_id}",
            )
            current = await self._repository.latest_generation_session(
                session,
                tenant.tenant_id,
                generation_session_id,
            )
            if current is None:
                raise self._not_found("generation session")
            if current.state != GenerationSessionState.PLANNED:
                return self.session_document(current)
            next_version = current.session_version + 1
            result_document = {
                **current.result_document,
                "state": GenerationSessionState.RUNNING.value,
                "started_at": started_at.isoformat(),
            }
            running = GenerationSessionRecord(
                session_snapshot_id=uuid5(
                    generation_session_id,
                    f"session-version:{next_version}",
                ),
                generation_session_id=generation_session_id,
                session_version=next_version,
                parent_session_snapshot_id=current.session_snapshot_id,
                learner_ref=current.learner_ref,
                course_id=current.course_id,
                topic1_graph_snapshot_id=current.topic1_graph_snapshot_id,
                topic1_graph_version=current.topic1_graph_version,
                topic2_profile_id=current.topic2_profile_id,
                topic2_profile_version=current.topic2_profile_version,
                topic2_path_snapshot_id=current.topic2_path_snapshot_id,
                topic2_path_version=current.topic2_path_version,
                personalization_policy_digest=current.personalization_policy_digest,
                requested_resources=current.requested_resources,
                state=GenerationSessionState.RUNNING,
                request_document=current.request_document,
                result_document=result_document,
                content_sha256=canonical_sha256(
                    {
                        "generation_session_id": str(generation_session_id),
                        "session_version": next_version,
                        "state": GenerationSessionState.RUNNING.value,
                        "request": current.request_document,
                        "result": result_document,
                    }
                ),
                created_by_subject=current.created_by_subject,
                frozen_at=started_at,
            )
            audit = await self._append_audit(
                session,
                tenant,
                action="GENERATION_WORKFLOW_STARTED",
                target_ref=str(generation_session_id),
                metadata=self.session_document(running),
            )
            await self._repository.append_generation_session(
                session,
                tenant.tenant_id,
                running,
                audit.event_id,
            )
            await self._append_outbox(
                session,
                tenant,
                event_type="topic3.workflow.started",
                payload=self.session_document(running),
                partition_key=self._partition_key(tenant.tenant_id, generation_session_id),
            )
            return self.session_document(running)

        await self._execute_mutation(
            operation="topic3.workflow.start",
            idempotency_key=f"topic3:{generation_session_id}:start:v1",
            request_document={"generation_session_id": str(generation_session_id)},
            callback=callback,
        )
        async with self._database.transaction(context=current_session_context()) as session:
            current = await self._repository.latest_generation_session(
                session,
                current_tenant().tenant_id,
                generation_session_id,
            )
        if current is None:
            raise self._not_found("generation session")
        return current

    async def mark_task_running(self, current: AgentTaskRecord) -> AgentTaskRecord:
        now = datetime.now(UTC)
        next_record = AgentTaskRecord(
            task_record_id=uuid5(current.task_id, f"task-version:{current.task_version + 1}"),
            task_id=current.task_id,
            task_version=current.task_version + 1,
            blueprint_id=current.blueprint_id,
            blueprint_version=current.blueprint_version,
            agent=current.agent,
            resource_type=current.resource_type,
            state=AgentTaskState.RUNNING,
            dependency_task_ids=current.dependency_task_ids,
            attempt=current.attempt + 1,
            max_attempts=current.max_attempts,
            timeout_seconds=current.timeout_seconds,
            request_document=current.request_document,
            result_document={},
            error_document={},
            request_sha256=current.request_sha256,
            result_sha256=None,
            started_at=now,
            completed_at=None,
        )

        async def callback(session: AsyncSession, tenant: TenantContext) -> dict[str, Any]:
            await self._assert_latest_task(session, tenant.tenant_id, current)
            audit = await self._append_audit(
                session,
                tenant,
                action="AGENT_TASK_STARTED",
                target_ref=str(current.task_id),
                metadata=self.task_document(next_record),
            )
            await self._repository.append_task(
                session,
                tenant.tenant_id,
                next_record,
                audit.event_id,
            )
            await self._append_outbox(
                session,
                tenant,
                event_type="topic3.agent-task.started",
                payload=self.task_document(next_record),
                partition_key=self._partition_key(tenant.tenant_id, current.blueprint_id),
            )
            return self.task_document(next_record)

        await self._execute_mutation(
            operation="topic3.task.start",
            idempotency_key=f"topic3:{current.task_id}:start:{next_record.task_version}",
            request_document=self.task_document(current),
            callback=callback,
        )
        return next_record

    async def complete_task(
        self,
        current: AgentTaskRecord,
        candidate: CandidateV1,
        chunks: Sequence[SSEChunkV1],
        invocation: ModelInvocationRecord | None,
    ) -> AgentTaskRecord:
        now = datetime.now(UTC)
        result_document = {
            "candidate_id": str(candidate.candidate_id),
            "candidate_version": candidate.candidate_version,
            "candidate_sha256": candidate.candidate_sha256,
            "stream_ids": sorted({str(chunk.stream_id) for chunk in chunks}),
            "fragment_ids": [str(chunk.fragment_id) for chunk in chunks],
        }
        next_record = AgentTaskRecord(
            task_record_id=uuid5(current.task_id, f"task-version:{current.task_version + 1}"),
            task_id=current.task_id,
            task_version=current.task_version + 1,
            blueprint_id=current.blueprint_id,
            blueprint_version=current.blueprint_version,
            agent=current.agent,
            resource_type=current.resource_type,
            state=AgentTaskState.SUCCEEDED,
            dependency_task_ids=current.dependency_task_ids,
            attempt=current.attempt,
            max_attempts=current.max_attempts,
            timeout_seconds=current.timeout_seconds,
            request_document=current.request_document,
            result_document=result_document,
            error_document={},
            request_sha256=current.request_sha256,
            result_sha256=canonical_sha256(result_document),
            started_at=current.started_at,
            completed_at=now,
        )

        async def callback(session: AsyncSession, tenant: TenantContext) -> dict[str, Any]:
            await self._assert_latest_task(session, tenant.tenant_id, current)
            audit = await self._append_audit(
                session,
                tenant,
                action="AGENT_TASK_COMPLETED",
                target_ref=str(current.task_id),
                metadata={
                    **self.task_document(next_record),
                    "candidate_sha256": candidate.candidate_sha256,
                    "stream_chunk_count": len(chunks),
                },
            )
            await self._repository.append_candidate(
                session,
                tenant.tenant_id,
                CandidateRecord(
                    candidate_record_id=uuid5(candidate.candidate_id, "candidate-record-v1"),
                    candidate=candidate,
                    frozen_at=now,
                ),
                audit.event_id,
            )
            if invocation is not None:
                await self._repository.append_invocation(
                    session,
                    tenant.tenant_id,
                    invocation,
                    audit.event_id,
                )
            await self._repository.append_stream_chunks(
                session,
                tenant.tenant_id,
                [
                    StreamChunkRecord(
                        stream_chunk_record_id=uuid5(chunk.fragment_id, "stream-record-v1"),
                        chunk=chunk,
                    )
                    for chunk in chunks
                ],
                audit.event_id,
            )
            await self._repository.append_task(
                session,
                tenant.tenant_id,
                next_record,
                audit.event_id,
            )
            payload = {
                **self.task_document(next_record),
                "candidate": candidate.model_dump(mode="json"),
                "stream_chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            }
            await self._append_outbox(
                session,
                tenant,
                event_type="topic3.agent-task.completed",
                payload=payload,
                partition_key=self._partition_key(tenant.tenant_id, current.blueprint_id),
            )
            return payload

        await self._execute_mutation(
            operation="topic3.task.complete",
            idempotency_key=f"topic3:{current.task_id}:complete:{next_record.task_version}",
            request_document={
                "task": self.task_document(current),
                "candidate_sha256": candidate.candidate_sha256,
                "fragment_digests": [chunk.data_sha256 for chunk in chunks],
            },
            callback=callback,
        )
        return next_record

    async def fail_task(
        self,
        current: AgentTaskRecord,
        error: LiyanError,
        invocation: ModelInvocationRecord | None,
    ) -> AgentTaskRecord:
        now = datetime.now(UTC)
        error_document = {
            "error_code": error.code.value,
            "category": error.category.value,
            "retriable": error.retriable,
            "safe_message": error.safe_message,
        }
        next_record = AgentTaskRecord(
            task_record_id=uuid5(current.task_id, f"task-version:{current.task_version + 1}"),
            task_id=current.task_id,
            task_version=current.task_version + 1,
            blueprint_id=current.blueprint_id,
            blueprint_version=current.blueprint_version,
            agent=current.agent,
            resource_type=current.resource_type,
            state=AgentTaskState.FAILED,
            dependency_task_ids=current.dependency_task_ids,
            attempt=current.attempt,
            max_attempts=current.max_attempts,
            timeout_seconds=current.timeout_seconds,
            request_document=current.request_document,
            result_document={},
            error_document=error_document,
            request_sha256=current.request_sha256,
            result_sha256=canonical_sha256(error_document),
            started_at=current.started_at,
            completed_at=now,
        )

        async def callback(session: AsyncSession, tenant: TenantContext) -> dict[str, Any]:
            await self._assert_latest_task(session, tenant.tenant_id, current)
            audit = await self._append_audit(
                session,
                tenant,
                action="AGENT_TASK_FAILED",
                target_ref=str(current.task_id),
                metadata={**self.task_document(next_record), "error": error_document},
            )
            if invocation is not None:
                await self._repository.append_invocation(
                    session,
                    tenant.tenant_id,
                    invocation,
                    audit.event_id,
                )
            await self._repository.append_task(
                session,
                tenant.tenant_id,
                next_record,
                audit.event_id,
            )
            payload = {**self.task_document(next_record), "error": error_document}
            await self._append_outbox(
                session,
                tenant,
                event_type="topic3.agent-task.failed",
                payload=payload,
                partition_key=self._partition_key(tenant.tenant_id, current.blueprint_id),
            )
            return payload

        await self._execute_mutation(
            operation="topic3.task.fail",
            idempotency_key=f"topic3:{current.task_id}:fail:{next_record.task_version}",
            request_document={"task": self.task_document(current), "error": error_document},
            callback=callback,
        )
        return next_record

    async def skip_task(
        self,
        current: AgentTaskRecord,
        *,
        reason: str,
    ) -> AgentTaskRecord:
        now = datetime.now(UTC)
        error_document = {
            "error_code": "LIYAN-TOPIC3-DEPENDENCY-FAILED",
            "category": ErrorCategory.TASK.value,
            "retriable": False,
            "safe_message": reason,
        }
        next_record = AgentTaskRecord(
            task_record_id=uuid5(current.task_id, f"task-version:{current.task_version + 1}"),
            task_id=current.task_id,
            task_version=current.task_version + 1,
            blueprint_id=current.blueprint_id,
            blueprint_version=current.blueprint_version,
            agent=current.agent,
            resource_type=current.resource_type,
            state=AgentTaskState.SKIPPED,
            dependency_task_ids=current.dependency_task_ids,
            attempt=current.attempt,
            max_attempts=current.max_attempts,
            timeout_seconds=current.timeout_seconds,
            request_document=current.request_document,
            result_document={},
            error_document=error_document,
            request_sha256=current.request_sha256,
            result_sha256=canonical_sha256(error_document),
            started_at=current.started_at,
            completed_at=now,
        )

        async def callback(session: AsyncSession, tenant: TenantContext) -> dict[str, Any]:
            await self._assert_latest_task(session, tenant.tenant_id, current)
            audit = await self._append_audit(
                session,
                tenant,
                action="AGENT_TASK_SKIPPED",
                target_ref=str(current.task_id),
                metadata={**self.task_document(next_record), "reason": reason},
            )
            await self._repository.append_task(
                session,
                tenant.tenant_id,
                next_record,
                audit.event_id,
            )
            payload = {**self.task_document(next_record), "reason": reason}
            await self._append_outbox(
                session,
                tenant,
                event_type="topic3.agent-task.skipped",
                payload=payload,
                partition_key=self._partition_key(tenant.tenant_id, current.blueprint_id),
            )
            return payload

        await self._execute_mutation(
            operation="topic3.task.skip",
            idempotency_key=f"topic3:{current.task_id}:skip:{next_record.task_version}",
            request_document={"task": self.task_document(current), "reason": reason},
            callback=callback,
        )
        return next_record

    async def finalize_workflow(
        self,
        generation_session_id: UUID,
        blueprint: Topic3ExecutionBlueprintV1,
        tasks: Sequence[AgentTaskRecord],
        candidates: Sequence[CandidateV1],
    ) -> Topic3GenerationResultV1:
        nonterminal = [
            task for task in tasks if task.state in {AgentTaskState.PENDING, AgentTaskState.RUNNING}
        ]
        if nonterminal:
            raise self._conflict("The Topic 3 workflow cannot finalize with active Agent tasks.")
        failed = [task.agent for task in tasks if task.state == AgentTaskState.FAILED]
        blocked = [
            task.agent
            for task in tasks
            if task.state in {AgentTaskState.SKIPPED, AgentTaskState.CANCELLED}
        ]
        succeeded = [task for task in tasks if task.state == AgentTaskState.SUCCEEDED]
        incomplete = failed + blocked
        if incomplete and blueprint.allow_partial and succeeded:
            state = GenerationSessionState.PARTIAL
        elif incomplete:
            state = GenerationSessionState.FAILED
        else:
            state = GenerationSessionState.COMPLETED
        completed_at = datetime.now(UTC)

        async def callback(session: AsyncSession, tenant: TenantContext) -> dict[str, Any]:
            await self._lock(
                session,
                f"workflow:{tenant.tenant_id}:{generation_session_id}",
            )
            current = await self._repository.latest_generation_session(
                session,
                tenant.tenant_id,
                generation_session_id,
            )
            if current is None:
                raise self._not_found("generation session")
            if current.state in {
                GenerationSessionState.COMPLETED,
                GenerationSessionState.PARTIAL,
                GenerationSessionState.FAILED,
                GenerationSessionState.CANCELLED,
            }:
                return {
                    "session_version": current.session_version,
                    **current.result_document,
                }
            result_document = {
                "session_version": current.session_version + 1,
                "blueprint_id": str(blueprint.blueprint_id),
                "blueprint_version": blueprint.blueprint_version,
                "candidate_ids": [str(candidate.candidate_id) for candidate in candidates],
                "failed_agents": [agent.value for agent in failed],
                "completed_at": completed_at.isoformat(),
                "state": state.value,
            }
            final = GenerationSessionRecord(
                session_snapshot_id=uuid5(
                    generation_session_id,
                    f"session-version:{current.session_version + 1}",
                ),
                generation_session_id=generation_session_id,
                session_version=current.session_version + 1,
                parent_session_snapshot_id=current.session_snapshot_id,
                learner_ref=current.learner_ref,
                course_id=current.course_id,
                topic1_graph_snapshot_id=current.topic1_graph_snapshot_id,
                topic1_graph_version=current.topic1_graph_version,
                topic2_profile_id=current.topic2_profile_id,
                topic2_profile_version=current.topic2_profile_version,
                topic2_path_snapshot_id=current.topic2_path_snapshot_id,
                topic2_path_version=current.topic2_path_version,
                personalization_policy_digest=current.personalization_policy_digest,
                requested_resources=current.requested_resources,
                state=state,
                request_document=current.request_document,
                result_document=result_document,
                content_sha256=canonical_sha256(result_document),
                created_by_subject=tenant.subject_ref,
                frozen_at=completed_at,
            )
            audit = await self._append_audit(
                session,
                tenant,
                action="GENERATION_WORKFLOW_FINALIZED",
                target_ref=str(generation_session_id),
                metadata=result_document,
            )
            await self._repository.append_generation_session(
                session,
                tenant.tenant_id,
                final,
                audit.event_id,
            )
            await self._append_outbox(
                session,
                tenant,
                event_type="topic3.workflow.finalized",
                payload={"generation_session_id": str(generation_session_id), **result_document},
                partition_key=self._partition_key(tenant.tenant_id, generation_session_id),
            )
            return result_document

        persisted = await self._execute_mutation(
            operation="topic3.workflow.finalize",
            idempotency_key=f"topic3:{generation_session_id}:finalize:v1",
            request_document={
                "blueprint_sha256": blueprint.blueprint_sha256,
                "tasks": [self.task_document(task) for task in tasks],
                "candidate_hashes": [candidate.candidate_sha256 for candidate in candidates],
            },
            callback=callback,
        )
        return Topic3GenerationResultV1(
            schema_version="topic3.generation-result.v1",
            generation_session_id=generation_session_id,
            session_version=int(persisted["session_version"]),
            state=state,
            blueprint=blueprint,
            tasks=[self.task_snapshot(task) for task in tasks],
            candidates=list(candidates),
            failed_agents=failed,
            completed_at=completed_at,
        )

    async def load_runtime(
        self,
        generation_session_id: UUID,
    ) -> tuple[
        GenerationSessionRecord,
        Topic3GenerationCommandV1,
        Topic2AgentContextV1,
        BlueprintRecord,
        list[AgentTaskRecord],
        list[CandidateRecord],
    ]:
        tenant = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            current = await self._repository.latest_generation_session(
                session,
                tenant.tenant_id,
                generation_session_id,
            )
            if current is None:
                raise self._not_found("generation session")
            self._assert_learner_access(tenant, current.learner_ref)
            initial = await self._repository.get_generation_session(
                session,
                tenant.tenant_id,
                generation_session_id,
                1,
            )
            if initial is None:
                raise self._not_found("initial generation session snapshot")
            blueprint_id = UUID(str(initial.result_document["blueprint_id"]))
            blueprint_version = str(initial.result_document["blueprint_version"])
            blueprint = await self._repository.get_blueprint(
                session,
                tenant.tenant_id,
                blueprint_id,
                blueprint_version,
            )
            if blueprint is None:
                raise self._not_found("execution blueprint")
            tasks = await self._repository.latest_tasks(
                session,
                tenant.tenant_id,
                blueprint_id,
                blueprint_version,
            )
            candidates = await self._repository.list_candidates(
                session,
                tenant.tenant_id,
                blueprint_id,
                blueprint_version,
            )
        return (
            current,
            Topic3GenerationCommandV1.model_validate(initial.request_document["command"]),
            Topic2AgentContextV1.model_validate(initial.request_document["personalization"]),
            blueprint,
            tasks,
            candidates,
        )

    async def list_workflows(
        self,
        learner_ref: str,
        course_id: str,
        *,
        limit: int,
    ) -> list[GenerationSessionRecord]:
        tenant = current_tenant()
        self._assert_learner_access(tenant, learner_ref)
        async with self._database.transaction(context=current_session_context()) as session:
            return await self._repository.list_generation_sessions(
                session,
                tenant.tenant_id,
                learner_ref,
                course_id,
                limit=limit,
            )

    async def list_stream_chunks(
        self,
        stream_id: UUID,
        *,
        after_index: int | None,
        limit: int,
    ) -> list[SSEChunkV1]:
        tenant = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            records = await self._repository.list_stream_chunks(
                session,
                tenant.tenant_id,
                stream_id,
                after_index=after_index,
                limit=limit,
            )
        return [record.chunk for record in records]

    async def _execute_mutation(
        self,
        *,
        operation: str,
        idempotency_key: str,
        request_document: dict[str, Any],
        callback: MutationCallback,
    ) -> dict[str, Any]:
        self._validate_idempotency_key(idempotency_key)
        digest = canonical_sha256({"operation": operation, "request": request_document})
        context = current_tenant()

        async def transaction(session: AsyncSession) -> dict[str, Any]:
            duplicate = await self._reserve_idempotency(
                session,
                context,
                idempotency_key,
                operation,
                digest,
            )
            if duplicate is not None:
                return duplicate
            result = await callback(session, context)
            await self._complete_idempotency(session, context, idempotency_key, result)
            return result

        try:
            return await self._database.run_transaction(
                transaction,
                context=current_session_context(),
                isolation=TransactionIsolation.SERIALIZABLE,
                retry_policy=TransactionRetryPolicy(max_attempts=3),
            )
        except IntegrityError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
            if sqlstate == "23505":
                raise self._conflict(
                    "The Topic 3 mutation conflicts with an existing version."
                ) from exc
            if sqlstate == "23503":
                raise self._contract_error(
                    "The Topic 3 mutation references a missing or mismatched frozen resource."
                ) from exc
            raise self._contract_error(
                "The Topic 3 mutation violates a persistence constraint."
            ) from exc

    async def _reserve_idempotency(
        self,
        session: AsyncSession,
        context: TenantContext,
        key: str,
        operation: str,
        digest: str,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        statement = (
            insert(IdempotencyRecordModel)
            .values(
                tenant_id=context.tenant_id,
                idempotency_key=key,
                operation=operation,
                request_digest=digest,
                state=IdempotencyStatus.PROCESSING.value,
                lease_owner=self._instance_id,
                lease_expires_at=now + timedelta(minutes=2),
                expires_at=now + IDEMPOTENCY_RETENTION,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    IdempotencyRecordModel.tenant_id,
                    IdempotencyRecordModel.idempotency_key,
                ]
            )
            .returning(IdempotencyRecordModel.idempotency_key)
        )
        inserted = (await session.execute(statement)).scalar_one_or_none()
        if inserted is not None:
            return None
        result = await session.execute(
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.tenant_id == context.tenant_id,
                IdempotencyRecordModel.idempotency_key == key,
            )
            .with_for_update()
        )
        record = result.scalar_one()
        if record.request_digest != digest or record.operation != operation:
            raise MessageConflictError(
                ErrorCode.MESSAGE_DUPLICATE_CONFLICT,
                "The idempotency key was reused for different Topic 3 content.",
            )
        if record.state == IdempotencyStatus.COMPLETED.value:
            if not isinstance(record.result_payload, dict):
                raise self._conflict("The completed Topic 3 idempotency result is unavailable.")
            return dict(record.result_payload)
        if record.lease_expires_at is not None and record.lease_expires_at > now:
            raise self._conflict("The idempotent Topic 3 operation is already in progress.")
        record.state = IdempotencyStatus.PROCESSING.value
        record.lease_owner = self._instance_id
        record.lease_expires_at = now + timedelta(minutes=2)
        record.expires_at = now + IDEMPOTENCY_RETENTION
        record.updated_at = now
        return None

    @staticmethod
    async def _complete_idempotency(
        session: AsyncSession,
        context: TenantContext,
        key: str,
        data: dict[str, Any],
    ) -> None:
        result = await session.execute(
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.tenant_id == context.tenant_id,
                IdempotencyRecordModel.idempotency_key == key,
            )
            .with_for_update()
        )
        record = result.scalar_one()
        record.state = IdempotencyStatus.COMPLETED.value
        record.lease_owner = None
        record.lease_expires_at = None
        record.response_status_code = 200
        record.result_payload = data
        record.updated_at = datetime.now(UTC)

    @staticmethod
    async def _append_audit(
        session: AsyncSession,
        context: TenantContext,
        *,
        action: str,
        target_ref: str,
        metadata: dict[str, Any],
    ) -> AuditRecord:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"audit:{context.tenant_id}"},
        )
        result = await session.execute(
            select(AuditEventModel)
            .where(AuditEventModel.tenant_id == context.tenant_id)
            .order_by(AuditEventModel.sequence.desc())
            .limit(1)
        )
        previous = result.scalar_one_or_none()
        draft = AuditDraft(
            tenant_id=context.tenant_id,
            category="TOPIC3",
            action=action,
            outcome="SUCCEEDED",
            actor_ref=context.subject_ref,
            target_ref=target_ref,
            trace_id=context.trace_id,
            envelope_id=None,
            metadata=metadata,
            occurred_at=datetime.now(UTC),
        )
        record = build_audit_record(
            draft,
            0 if previous is None else previous.sequence + 1,
            GENESIS_HASH if previous is None else previous.event_hash,
        )
        session.add(
            AuditEventModel(
                event_id=record.event_id,
                tenant_id=record.tenant_id,
                sequence=record.sequence,
                category=record.category,
                action=record.action,
                outcome=record.outcome,
                actor_ref=record.actor_ref,
                target_ref=record.target_ref,
                trace_id=record.trace_id,
                envelope_id=None,
                event_metadata=record.metadata,
                occurred_at=record.occurred_at,
                previous_hash=record.previous_hash,
                event_hash=record.event_hash,
            )
        )
        await session.flush()
        return record

    async def _append_outbox(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        event_type: str,
        payload: dict[str, Any],
        partition_key: str,
    ) -> None:
        await self._lock(session, f"outbox:{partition_key}")
        result = await session.execute(
            select(func.coalesce(func.max(OutboxMessageModel.sequence) + 1, 0)).where(
                OutboxMessageModel.tenant_id == context.tenant_id,
                OutboxMessageModel.partition_key == partition_key,
            )
        )
        sequence = int(result.scalar_one())
        now = datetime.now(UTC)
        correlation_id = uuid4()
        envelope = Topic3EnvelopeV1(
            envelope_id=uuid4(),
            event_type=event_type,
            message_kind=MessageKind.EVENT,
            tenant_id=context.tenant_id,
            session_id=context.session_id or correlation_id,
            subject_ref=context.subject_ref,
            correlation_id=correlation_id,
            causation_id=None,
            sequence=sequence,
            partition_key=partition_key,
            producer=ProducerMetadataV1(
                agent=None,
                service="topic3-generation-service",
                instance_id=self._instance_id,
                build_version="topic3-v1",
            ),
            delivery=DeliveryMetadataV1(
                idempotency_key=f"topic3:{canonical_sha256(payload)}",
                available_at=now,
                expires_at=now + OUTBOX_RETENTION,
            ),
            resource=None,
            trace_id=context.trace_id,
            span_id=None,
            created_at=now,
            error=None,
            payload=payload,
        )
        await self._outbox.append(
            session,
            OutboxMessage(
                outbox_id=uuid4(),
                tenant_id=context.tenant_id,
                envelope=envelope,
                created_at=now,
                available_at=now,
                published_at=None,
                max_attempts=envelope.delivery.max_attempts,
            ),
        )

    async def _assert_latest_task(
        self,
        session: AsyncSession,
        tenant_id: str,
        expected: AgentTaskRecord,
    ) -> None:
        await self._lock(session, f"task:{tenant_id}:{expected.task_id}")
        tasks = await self._repository.latest_tasks(
            session,
            tenant_id,
            expected.blueprint_id,
            expected.blueprint_version,
        )
        latest = next((item for item in tasks if item.task_id == expected.task_id), None)
        if latest is None:
            raise self._not_found("Agent task")
        if latest.task_version != expected.task_version or latest.state != expected.state:
            raise self._version_conflict("The Agent task transition is based on a stale snapshot.")

    @staticmethod
    async def _lock(session: AsyncSession, lock_key: str) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )

    @staticmethod
    def _pending_task(
        step,
        blueprint: Topic3ExecutionBlueprintV1,
        command: Topic3GenerationCommandV1,
        created_at: datetime,
    ) -> AgentTaskRecord:
        request_document = {
            "generation_session_id": str(command.generation_session_id),
            "command": command.model_dump(mode="json"),
            "step": step.model_dump(mode="json"),
        }
        return AgentTaskRecord(
            task_record_id=uuid5(step.task_id, "task-version:1"),
            task_id=step.task_id,
            task_version=1,
            blueprint_id=blueprint.blueprint_id,
            blueprint_version=blueprint.blueprint_version,
            agent=step.agent,
            resource_type=step.resource_type,
            state=AgentTaskState.PENDING,
            dependency_task_ids=tuple(step.dependency_task_ids),
            attempt=0,
            max_attempts=step.max_attempts,
            timeout_seconds=step.timeout_seconds,
            request_document=request_document,
            result_document={},
            error_document={},
            request_sha256=canonical_sha256(request_document),
            result_sha256=None,
            started_at=None,
            completed_at=None,
        )

    @staticmethod
    def _session_record(
        *,
        command: Topic3GenerationCommandV1,
        graph: Topic1GraphSnapshotV1,
        personalization: Topic2AgentContextV1,
        session_version: int,
        parent_session_snapshot_id: UUID | None,
        state: GenerationSessionState,
        request_document: dict[str, Any],
        result_document: dict[str, Any],
        subject_ref: str,
        frozen_at: datetime,
    ) -> GenerationSessionRecord:
        hash_document = {
            "generation_session_id": str(command.generation_session_id),
            "session_version": session_version,
            "state": state.value,
            "request": request_document,
            "result": result_document,
        }
        return GenerationSessionRecord(
            session_snapshot_id=uuid5(
                command.generation_session_id,
                f"session-version:{session_version}",
            ),
            generation_session_id=command.generation_session_id,
            session_version=session_version,
            parent_session_snapshot_id=parent_session_snapshot_id,
            learner_ref=command.learner_ref,
            course_id=command.course_id,
            topic1_graph_snapshot_id=graph.snapshot_id,
            topic1_graph_version=graph.graph_version,
            topic2_profile_id=personalization.profile.profile_id,
            topic2_profile_version=personalization.profile.profile_version,
            topic2_path_snapshot_id=(personalization.learning_path.snapshot.path_snapshot_id),
            topic2_path_version=personalization.learning_path.snapshot.path_version,
            personalization_policy_digest=personalization.personalization_policy_digest,
            requested_resources=tuple(command.requested_resources),
            state=state,
            request_document=request_document,
            result_document=result_document,
            content_sha256=canonical_sha256(hash_document),
            created_by_subject=subject_ref,
            frozen_at=frozen_at,
        )

    @staticmethod
    def task_snapshot(record: AgentTaskRecord) -> Topic3AgentTaskSnapshotV1:
        candidate_id = record.result_document.get("candidate_id")
        candidate_version = record.result_document.get("candidate_version")
        return Topic3AgentTaskSnapshotV1(
            schema_version="topic3.agent-task-snapshot.v1",
            task_id=record.task_id,
            task_version=record.task_version,
            blueprint_id=record.blueprint_id,
            blueprint_version=record.blueprint_version,
            agent=record.agent,
            resource_type=record.resource_type,
            state=record.state,
            attempt=record.attempt,
            max_attempts=record.max_attempts,
            request_sha256=record.request_sha256,
            result_sha256=record.result_sha256,
            candidate_id=None if candidate_id is None else UUID(str(candidate_id)),
            candidate_version=(None if candidate_version is None else int(candidate_version)),
            error_code=record.error_document.get("error_code"),
            started_at=record.started_at,
            completed_at=record.completed_at,
        )

    @classmethod
    def task_document(cls, record: AgentTaskRecord) -> dict[str, Any]:
        return cls.task_snapshot(record).model_dump(mode="json")

    @staticmethod
    def session_document(record: GenerationSessionRecord) -> dict[str, Any]:
        return {
            "generation_session_id": str(record.generation_session_id),
            "session_version": record.session_version,
            "learner_ref": record.learner_ref,
            "course_id": record.course_id,
            "state": record.state.value,
            "requested_resources": [value.value for value in record.requested_resources],
            "result": record.result_document,
            "content_sha256": record.content_sha256,
            "frozen_at": record.frozen_at.isoformat(),
        }

    @staticmethod
    def _assert_learner_access(context: TenantContext, learner_ref: str) -> None:
        privileged = bool({"topic3:learner:any", "topic3:admin"} & context.scopes)
        if learner_ref != context.subject_ref and not privileged:
            raise LiyanError(
                ErrorCode.AUTH_FORBIDDEN,
                "The authenticated identity cannot access another learner's generation state.",
                category=ErrorCategory.AUTH,
                status_code=403,
            )

    @staticmethod
    def _partition_key(tenant_id: str, workflow_id: UUID) -> str:
        return f"topic3:{tenant_id}:{workflow_id}"

    @staticmethod
    def _validate_idempotency_key(value: str) -> None:
        if not 16 <= len(value) <= 160:
            raise Topic3Service._contract_error(
                "The idempotency key must contain between 16 and 160 characters."
            )

    @staticmethod
    def _not_found(resource: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC3_NOT_FOUND,
            f"The requested Topic 3 {resource} does not exist.",
            category=ErrorCategory.CONTRACT,
            status_code=404,
        )

    @staticmethod
    def _conflict(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC3_CONFLICT,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=409,
        )

    @staticmethod
    def _version_conflict(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC3_VERSION_CONFLICT,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=409,
        )

    @staticmethod
    def _contract_error(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.CONTRACT_INVALID,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=422,
        )
