from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import Topic1GraphSnapshotV1
from liyans_contracts.topic2 import Topic2AgentContextV1
from liyans_contracts.topic3 import (
    AgentTaskState,
    CandidateV1,
    Topic3GenerationCommandV1,
    Topic3GenerationResultV1,
)
from sqlalchemy import text

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError, OperationTimeoutError
from liyans.core.tenant import TenantContext, current_tenant, tenant_scope
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.domains.topic2.orchestrator import Topic2Orchestrator
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.session import DatabaseSessionManager
from liyans.infrastructure.tasks.queue import TaskPriority, TaskRequest

from .agents import AgentExecutionContext, AgentExecutionFailure, Topic3AgentRegistry
from .blueprint import ImmutableBlueprintPlanner
from .entities import AgentTaskRecord, ModelInvocationRecord
from .service import Topic3Service
from .streaming import Topic3StreamCoordinator

logger = logging.getLogger(__name__)
TOPIC3_WORKFLOW_TASK = "topic3.execute-workflow"


class Topic3Orchestrator:
    def __init__(
        self,
        database: DatabaseSessionManager,
        topic1_repository: PostgresTopic1Repository,
        topic2_orchestrator: Topic2Orchestrator,
        service: Topic3Service,
        planner: ImmutableBlueprintPlanner,
        agents: Topic3AgentRegistry,
        stream: Topic3StreamCoordinator,
    ) -> None:
        self._database = database
        self._topic1_repository = topic1_repository
        self._topic2_orchestrator = topic2_orchestrator
        self._service = service
        self._planner = planner
        self._agents = agents
        self._stream = stream

    async def prepare(
        self,
        command: Topic3GenerationCommandV1,
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        graph = await self._latest_graph(command.course_id)
        personalization = Topic2AgentContextV1.model_validate(
            await self._topic2_orchestrator.agent_context(
                command.learner_ref,
                command.course_id,
            )
        )
        decision = self._planner.build(command, graph, personalization)
        return await self._service.create_workflow(
            command,
            graph,
            personalization,
            decision,
            idempotency_key=idempotency_key,
        )

    async def execute(self, generation_session_id: UUID) -> Topic3GenerationResultV1:
        async with self._workflow_execution_lock(generation_session_id):
            return await self._execute_locked(generation_session_id)

    async def _execute_locked(self, generation_session_id: UUID) -> Topic3GenerationResultV1:
        await self._service.start_workflow(generation_session_id)
        (
            current_session,
            command,
            personalization,
            blueprint_record,
            tasks,
            candidate_records,
        ) = await self._service.load_runtime(generation_session_id)
        blueprint = blueprint_record.blueprint
        if current_session.state.value in {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}:
            return self._result_from_runtime(
                current_session.session_version,
                current_session.state,
                blueprint,
                tasks,
                [record.candidate for record in candidate_records],
            )
        graph = await self._graph_snapshot(blueprint.topic1_graph_snapshot_id)
        if graph.content_sha256 != blueprint.topic1_graph_sha256:
            raise self._generation_error(
                "The frozen Topic 1 graph snapshot failed integrity binding."
            )
        await self._execute_dag(
            command,
            graph,
            personalization,
            blueprint,
            tasks,
            [record.candidate for record in candidate_records],
        )
        _, _, _, _, final_tasks, final_candidates = await self._service.load_runtime(
            generation_session_id
        )
        return await self._service.finalize_workflow(
            generation_session_id,
            blueprint,
            final_tasks,
            [record.candidate for record in final_candidates],
        )

    @asynccontextmanager
    async def _workflow_execution_lock(
        self,
        generation_session_id: UUID,
    ) -> AsyncIterator[None]:
        tenant_id = current_tenant().tenant_id
        lock_key = f"topic3-execution:{tenant_id}:{generation_session_id}"
        async with self._database.engine.connect() as connection:
            acquired = bool(
                await connection.scalar(
                    text("SELECT pg_try_advisory_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": lock_key},
                )
            )
            if not acquired:
                raise LiyanError(
                    ErrorCode.TOPIC3_CONFLICT,
                    "The Topic 3 workflow is already executing on another worker.",
                    category=ErrorCategory.TASK,
                    retriable=True,
                    status_code=409,
                )
            try:
                yield
            finally:
                try:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(hashtextextended(:lock_key, 0))"),
                        {"lock_key": lock_key},
                    )
                except Exception:
                    logger.exception(
                        "Topic 3 workflow advisory unlock failed session_id=%s",
                        generation_session_id,
                    )

    def queue_request(
        self,
        generation_session_id: UUID,
        context: TenantContext,
    ) -> TaskRequest:
        return TaskRequest(
            task_type=TOPIC3_WORKFLOW_TASK,
            tenant_id=context.tenant_id,
            task_id=uuid5(generation_session_id, "topic3-workflow-task"),
            payload={
                "generation_session_id": str(generation_session_id),
                "subject_ref": context.subject_ref,
                "trace_id": context.trace_id,
                "session_id": None if context.session_id is None else str(context.session_id),
            },
            priority=TaskPriority.NORMAL,
            timeout_seconds=900.0,
            max_attempts=2,
            expires_at=datetime.now(UTC) + timedelta(hours=2),
            correlation_id=generation_session_id,
        )

    async def handle_queue_task(self, request: TaskRequest) -> dict[str, object]:
        if request.task_type != TOPIC3_WORKFLOW_TASK:
            raise ValueError("unexpected Topic 3 task type")
        session_value = request.payload.get("session_id")
        context = TenantContext(
            tenant_id=request.tenant_id,
            subject_ref=str(request.payload["subject_ref"]),
            roles=frozenset({"topic3-worker"}),
            scopes=frozenset({"topic3:admin", "topic3:learner:any"}),
            trace_id=str(request.payload["trace_id"]),
            session_id=None if session_value is None else UUID(str(session_value)),
        )
        with tenant_scope(context):
            result = await self.execute(UUID(str(request.payload["generation_session_id"])))
        return result.model_dump(mode="json")

    async def _execute_dag(
        self,
        command: Topic3GenerationCommandV1,
        graph: Topic1GraphSnapshotV1,
        personalization: Topic2AgentContextV1,
        blueprint,
        tasks: list[AgentTaskRecord],
        candidates: list[CandidateV1],
    ) -> None:
        task_by_id = {task.task_id: task for task in tasks}
        candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
        step_by_id = {step.task_id: step for step in blueprint.steps}
        while True:
            actionable = [
                task
                for task in task_by_id.values()
                if task.state in {AgentTaskState.PENDING, AgentTaskState.RUNNING}
                or (
                    task.state == AgentTaskState.FAILED
                    and bool(task.error_document.get("retriable"))
                    and task.attempt < task.max_attempts
                )
            ]
            if not actionable:
                return
            for task in list(actionable):
                failed_dependencies = [
                    dependency
                    for dependency in task.dependency_task_ids
                    if task_by_id[dependency].state
                    in {AgentTaskState.FAILED, AgentTaskState.SKIPPED, AgentTaskState.CANCELLED}
                ]
                if failed_dependencies:
                    skipped = await self._service.skip_task(
                        task,
                        reason="A required upstream Agent did not produce an accepted candidate.",
                    )
                    task_by_id[task.task_id] = skipped
            ready = [
                task
                for task in task_by_id.values()
                if (
                    task.state in {AgentTaskState.PENDING, AgentTaskState.RUNNING}
                    or (
                        task.state == AgentTaskState.FAILED
                        and bool(task.error_document.get("retriable"))
                        and task.attempt < task.max_attempts
                    )
                )
                and all(
                    task_by_id[dependency].state == AgentTaskState.SUCCEEDED
                    for dependency in task.dependency_task_ids
                )
            ]
            if not ready:
                unresolved = [
                    task
                    for task in task_by_id.values()
                    if task.state in {AgentTaskState.PENDING, AgentTaskState.RUNNING}
                ]
                for task in unresolved:
                    task_by_id[task.task_id] = await self._service.skip_task(
                        task,
                        reason="The immutable Blueprint dependency graph could not make progress.",
                    )
                return
            batch = sorted(ready, key=lambda task: step_by_id[task.task_id].ordinal)[
                : blueprint.max_parallelism
            ]
            outcomes = await asyncio.gather(
                *(
                    self._run_task(
                        command,
                        graph,
                        personalization,
                        blueprint,
                        step_by_id[task.task_id],
                        task,
                        task_by_id,
                        candidate_by_id,
                    )
                    for task in batch
                )
            )
            for task, candidate in outcomes:
                task_by_id[task.task_id] = task
                if candidate is not None:
                    candidate_by_id[candidate.candidate_id] = candidate

    async def _run_task(
        self,
        command,
        graph,
        personalization,
        blueprint,
        step,
        initial: AgentTaskRecord,
        task_by_id: dict[UUID, AgentTaskRecord],
        candidate_by_id: dict[UUID, CandidateV1],
    ) -> tuple[AgentTaskRecord, CandidateV1 | None]:
        tenant_id = current_tenant().tenant_id
        current = initial
        while True:
            if current.state != AgentTaskState.RUNNING:
                current = await self._service.mark_task_running(current)
            await self._publish_progress(command, current)
            dependencies: list[CandidateV1] = []
            for dependency_id in current.dependency_task_ids:
                dependency_task = task_by_id[dependency_id]
                candidate_id = UUID(str(dependency_task.result_document["candidate_id"]))
                dependencies.append(candidate_by_id[candidate_id])
            agent_context = AgentExecutionContext(
                command=command,
                graph=graph,
                personalization=personalization,
                blueprint=blueprint,
                step=step,
                attempt=current.attempt,
                dependency_candidates=tuple(dependencies),
            )
            try:
                async with asyncio.timeout(step.timeout_seconds):
                    outcome = await self._agents.require(step.agent).execute(agent_context)
            except TimeoutError:
                error = OperationTimeoutError(f"topic3-agent:{step.agent.value}")
                current = await self._service.fail_task(current, error, None)
                await self._publish_progress(command, current)
                if current.attempt < current.max_attempts:
                    continue
                return current, None
            except AgentExecutionFailure as exc:
                error = self._normalize_error(exc.cause)
                invocation = self._failed_invocation(current, exc, error)
                current = await self._service.fail_task(current, error, invocation)
                await self._publish_progress(command, current)
                if error.retriable and current.attempt < current.max_attempts:
                    continue
                return current, None
            except Exception as exc:
                error = self._normalize_error(exc)
                current = await self._service.fail_task(current, error, None)
                await self._publish_progress(command, current)
                if error.retriable and current.attempt < current.max_attempts:
                    continue
                return current, None
            chunks = self._stream.candidate_chunks(outcome.candidate)
            invocation = self._successful_invocation(current, outcome)
            current = await self._service.complete_task(
                current,
                outcome.candidate,
                chunks,
                invocation,
            )
            try:
                await self._stream.publish_chunks(tenant_id, chunks)
                await self._publish_progress(command, current)
            except Exception:
                logger.exception(
                    "Topic 3 low-latency SSE publication failed after durable commit task_id=%s",
                    current.task_id,
                )
            return current, outcome.candidate

    async def _publish_progress(
        self,
        command: Topic3GenerationCommandV1,
        task: AgentTaskRecord,
    ) -> None:
        try:
            await self._stream.publish_progress(
                current_tenant().tenant_id,
                generation_session_id=str(command.generation_session_id),
                task_id=str(task.task_id),
                agent=task.agent.value,
                state=task.state.value,
                attempt=task.attempt,
            )
        except Exception:
            logger.exception(
                "Topic 3 progress SSE publication failed task_id=%s state=%s",
                task.task_id,
                task.state.value,
            )

    @staticmethod
    def _successful_invocation(current, outcome) -> ModelInvocationRecord | None:
        if outcome.provider_result is None or outcome.provider_request is None:
            return None
        result = outcome.provider_result
        request = outcome.provider_request
        return ModelInvocationRecord(
            invocation_id=uuid5(current.task_id, f"invocation:{current.attempt}"),
            task_id=current.task_id,
            task_version=current.task_version,
            provider_alias=request.provider_alias,
            model_alias=request.model_alias,
            provider_request_id=result.request_id,
            state="SUCCEEDED",
            request_sha256=canonical_sha256(request.model_dump(mode="json")),
            response_sha256=result.response_sha256,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=max(
                0, int((result.completed_at - result.started_at).total_seconds() * 1000)
            ),
            error_document={},
            started_at=result.started_at,
            completed_at=result.completed_at,
        )

    @staticmethod
    def _failed_invocation(
        current: AgentTaskRecord,
        failure: AgentExecutionFailure,
        error: LiyanError,
    ) -> ModelInvocationRecord:
        result = failure.provider_result
        return ModelInvocationRecord(
            invocation_id=uuid5(current.task_id, f"invocation:{current.attempt}"),
            task_id=current.task_id,
            task_version=current.task_version,
            provider_alias=failure.request.provider_alias,
            model_alias=failure.provider_model_alias,
            provider_request_id=(
                result.request_id if result is not None else str(failure.request.request_id)
            ),
            state="TIMEOUT" if error.category == ErrorCategory.TIMEOUT else "FAILED",
            request_sha256=canonical_sha256(failure.request.model_dump(mode="json")),
            response_sha256=None if result is None else result.response_sha256,
            input_tokens=None if result is None else result.input_tokens,
            output_tokens=None if result is None else result.output_tokens,
            latency_ms=max(
                0,
                int((failure.completed_at - failure.started_at).total_seconds() * 1000),
            ),
            error_document={
                "error_code": error.code.value,
                "category": error.category.value,
                "retriable": error.retriable,
                "safe_message": error.safe_message,
            },
            started_at=failure.started_at,
            completed_at=failure.completed_at,
        )

    async def _latest_graph(self, course_id: str) -> Topic1GraphSnapshotV1:
        tenant = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            snapshot = await self._topic1_repository.latest_snapshot(
                session,
                tenant.tenant_id,
                course_id,
            )
        if snapshot is None:
            raise self._not_found("accepted Topic 1 graph snapshot")
        return snapshot

    async def _graph_snapshot(self, snapshot_id: UUID) -> Topic1GraphSnapshotV1:
        tenant = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            snapshot = await self._topic1_repository.get_snapshot(
                session,
                tenant.tenant_id,
                snapshot_id,
            )
        if snapshot is None:
            raise self._not_found("bound Topic 1 graph snapshot")
        return snapshot

    @staticmethod
    def _normalize_error(exc: Exception) -> LiyanError:
        if isinstance(exc, LiyanError):
            return exc
        return LiyanError(
            ErrorCode.TOPIC3_GENERATION_FAILED,
            "The Topic 3 Agent failed without exposing internal exception details.",
            category=ErrorCategory.INTERNAL,
            retriable=False,
            status_code=500,
        )

    @staticmethod
    def _result_from_runtime(
        session_version,
        state,
        blueprint,
        tasks,
        candidates,
    ) -> Topic3GenerationResultV1:
        completed = max(
            (task.completed_at for task in tasks if task.completed_at is not None),
            default=blueprint.created_at,
        )
        return Topic3GenerationResultV1(
            schema_version="topic3.generation-result.v1",
            generation_session_id=blueprint.generation_session_id,
            session_version=session_version,
            state=state,
            blueprint=blueprint,
            tasks=[Topic3Service.task_snapshot(task) for task in tasks],
            candidates=candidates,
            failed_agents=[task.agent for task in tasks if task.state == AgentTaskState.FAILED],
            completed_at=completed,
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
    def _generation_error(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC3_GENERATION_FAILED,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=409,
        )
