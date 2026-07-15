from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from liyans_contracts.enums import ResourceType
from liyans_contracts.topic3 import AgentTaskState, GenerationSessionState
from topic3_support import generation_command, graph_snapshot, personalization_context

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.domains.topic3.agents.mindmap import MindMapAgent
from liyans.domains.topic3.blueprint import ImmutableBlueprintPlanner
from liyans.domains.topic3.entities import (
    AgentTaskRecord,
    BlueprintRecord,
    CandidateRecord,
    GenerationSessionRecord,
    StreamChunkRecord,
)
from liyans.domains.topic3.service import Topic3Service
from liyans.domains.topic3.streaming import Topic3StreamCoordinator
from liyans.infrastructure.streaming.sse import InMemorySSEReplayLog, SSEBroker


class FakeSession:
    def in_transaction(self) -> bool:
        return True


class FakeDatabase:
    @asynccontextmanager
    async def transaction(self, **_kwargs):
        yield FakeSession()


class MemoryRepository:
    def __init__(self) -> None:
        self.sessions: list[GenerationSessionRecord] = []
        self.blueprints: list[BlueprintRecord] = []
        self.tasks: list[AgentTaskRecord] = []
        self.candidates: list[CandidateRecord] = []
        self.invocations: list[object] = []
        self.chunks: list[StreamChunkRecord] = []

    async def append_generation_session(self, _session, _tenant, record, _audit) -> None:
        self.sessions.append(record)

    async def latest_generation_session(self, _session, _tenant, generation_session_id):
        matches = [
            item for item in self.sessions if item.generation_session_id == generation_session_id
        ]
        return max(matches, key=lambda item: item.session_version, default=None)

    async def get_generation_session(self, _session, _tenant, generation_session_id, version):
        return next(
            (
                item
                for item in self.sessions
                if item.generation_session_id == generation_session_id
                and item.session_version == version
            ),
            None,
        )

    async def list_generation_sessions(
        self,
        _session,
        _tenant,
        learner_ref,
        course_id,
        *,
        limit,
    ):
        logical_ids = {
            item.generation_session_id
            for item in self.sessions
            if item.learner_ref == learner_ref and item.course_id == course_id
        }
        return [
            max(
                (item for item in self.sessions if item.generation_session_id == logical_id),
                key=lambda item: item.session_version,
            )
            for logical_id in list(logical_ids)[:limit]
        ]

    async def append_blueprint(self, _session, _tenant, record, _audit) -> None:
        self.blueprints.append(record)

    async def get_blueprint(self, _session, _tenant, blueprint_id, blueprint_version):
        return next(
            (
                item
                for item in self.blueprints
                if item.blueprint.blueprint_id == blueprint_id
                and item.blueprint.blueprint_version == blueprint_version
            ),
            None,
        )

    async def append_task(self, _session, _tenant, record, _audit) -> None:
        self.tasks.append(record)

    async def latest_tasks(self, _session, _tenant, blueprint_id, blueprint_version):
        task_ids = {
            item.task_id
            for item in self.tasks
            if item.blueprint_id == blueprint_id and item.blueprint_version == blueprint_version
        }
        return [
            max(
                (item for item in self.tasks if item.task_id == task_id),
                key=lambda item: item.task_version,
            )
            for task_id in task_ids
        ]

    async def append_candidate(self, _session, _tenant, record, _audit) -> None:
        self.candidates.append(record)

    async def list_candidates(self, _session, _tenant, blueprint_id, blueprint_version):
        return [
            item
            for item in self.candidates
            if item.candidate.blueprint_id == blueprint_id
            and item.candidate.blueprint_version == blueprint_version
        ]

    async def append_invocation(self, _session, _tenant, record, _audit) -> None:
        self.invocations.append(record)

    async def append_stream_chunks(self, _session, _tenant, records, _audit) -> None:
        self.chunks.extend(records)

    async def list_stream_chunks(
        self,
        _session,
        _tenant,
        stream_id,
        *,
        after_index,
        limit,
    ):
        values = [item for item in self.chunks if item.chunk.stream_id == stream_id]
        if after_index is not None:
            values = [item for item in values if item.chunk.chunk_index > after_index]
        return values[:limit]


class HarnessTopic3Service(Topic3Service):
    def __init__(self, repository: MemoryRepository) -> None:
        super().__init__(
            FakeDatabase(),
            repository,
            outbox=None,
            instance_id="test-topic3",
        )
        self.events: list[tuple[str, dict]] = []

    async def _execute_mutation(self, *, callback, **_kwargs):
        return await callback(FakeSession(), self._context())

    async def _append_audit(self, _session, _context, **_kwargs):
        return SimpleNamespace(event_id=uuid4())

    async def _append_outbox(self, _session, _context, *, event_type, payload, **_kwargs):
        self.events.append((event_type, payload))

    async def _assert_latest_task(self, _session, tenant_id, expected) -> None:
        tasks = await self._repository.latest_tasks(
            FakeSession(),
            tenant_id,
            expected.blueprint_id,
            expected.blueprint_version,
        )
        latest = next(item for item in tasks if item.task_id == expected.task_id)
        if latest.task_version != expected.task_version:
            raise self._version_conflict("stale")

    @staticmethod
    async def _lock(_session, _lock_key: str) -> None:
        return None

    @staticmethod
    def _context() -> TenantContext:
        return TenantContext(
            tenant_id="tenant-a",
            subject_ref="subject:student",
            roles=frozenset(),
            scopes=frozenset({"topic3:admin"}),
            trace_id="a" * 32,
        )


@pytest.mark.asyncio
async def test_service_persists_complete_immutable_workflow_lifecycle() -> None:
    graph = graph_snapshot()
    personalization = personalization_context(graph)
    command = generation_command(resources=[ResourceType.MIND_MAP])
    decision = ImmutableBlueprintPlanner().build(command, graph, personalization)
    repository = MemoryRepository()
    service = HarnessTopic3Service(repository)
    with tenant_scope(service._context()):
        created = await service.create_workflow(
            command,
            graph,
            personalization,
            decision,
            idempotency_key="topic3-service-create-0001",
        )
        await service.start_workflow(command.generation_session_id)
        pending = repository.tasks[-1]
        running = await service.mark_task_running(pending)
        agent_context = SimpleNamespace(
            command=command,
            graph=graph,
            personalization=personalization,
            blueprint=decision.blueprint,
            step=decision.blueprint.steps[0],
            attempt=running.attempt,
            dependency_candidates=(),
        )
        outcome = await MindMapAgent().execute(agent_context)
        coordinator = Topic3StreamCoordinator(
            SSEBroker(InMemorySSEReplayLog()),
            max_chunk_bytes=1024,
        )
        chunks = coordinator.candidate_chunks(outcome.candidate)
        completed = await service.complete_task(
            running,
            outcome.candidate,
            chunks,
            invocation=None,
        )
        result = await service.finalize_workflow(
            command.generation_session_id,
            decision.blueprint,
            [completed],
            [outcome.candidate],
        )
        runtime = await service.load_runtime(command.generation_session_id)
        history = await service.list_workflows(command.learner_ref, command.course_id, limit=10)
        persisted_chunks = await service.list_stream_chunks(
            chunks[0].stream_id,
            after_index=None,
            limit=100,
        )

    assert created["session_version"] == 1
    assert result.state == GenerationSessionState.COMPLETED
    assert result.tasks[0].state == AgentTaskState.SUCCEEDED
    assert len(repository.sessions) == 3
    assert repository.sessions[0].parent_session_snapshot_id is None
    assert (
        repository.sessions[1].parent_session_snapshot_id
        == repository.sessions[0].session_snapshot_id
    )
    assert (
        repository.sessions[2].parent_session_snapshot_id
        == repository.sessions[1].session_snapshot_id
    )
    assert runtime[0].state == GenerationSessionState.COMPLETED
    assert history[0].session_version == 3
    assert persisted_chunks == chunks
    assert {event_type for event_type, _ in service.events} >= {
        "topic3.workflow.created",
        "topic3.agent-task.started",
        "topic3.agent-task.completed",
        "topic3.workflow.finalized",
    }


@pytest.mark.asyncio
async def test_service_records_failure_skip_and_security_boundaries() -> None:
    graph = graph_snapshot()
    personalization = personalization_context(graph)
    command = generation_command(resources=[ResourceType.LECTURER_DOC, ResourceType.GRADIENT_QUIZ])
    decision = ImmutableBlueprintPlanner().build(command, graph, personalization)
    repository = MemoryRepository()
    service = HarnessTopic3Service(repository)
    with tenant_scope(service._context()):
        await service.create_workflow(
            command,
            graph,
            personalization,
            decision,
            idempotency_key="topic3-service-create-0002",
        )
        await service.start_workflow(command.generation_session_id)
        lecturer, tester = sorted(repository.tasks, key=lambda item: item.agent.value)
        if lecturer.agent.value != "Lecturer":
            lecturer, tester = tester, lecturer
        running = await service.mark_task_running(lecturer)
        failed = await service.fail_task(
            running,
            LiyanError(
                ErrorCode.TOPIC3_PROVIDER_UNAVAILABLE,
                "Provider unavailable.",
                category=ErrorCategory.PROVIDER,
                retriable=False,
                status_code=503,
            ),
            invocation=None,
        )
        skipped = await service.skip_task(tester, reason="Lecturer failed.")
        result = await service.finalize_workflow(
            command.generation_session_id,
            decision.blueprint,
            [failed, skipped],
            [],
        )
    assert failed.state == AgentTaskState.FAILED
    assert skipped.state == AgentTaskState.SKIPPED
    assert result.state == GenerationSessionState.FAILED
    assert result.failed_agents == [failed.agent]

    denied_context = replace_context(
        service._context(), subject_ref="subject:other", scopes=frozenset()
    )
    with tenant_scope(denied_context), pytest.raises(LiyanError) as denied:
        await service.list_workflows(command.learner_ref, command.course_id, limit=10)
    assert denied.value.code == ErrorCode.AUTH_FORBIDDEN
    with pytest.raises(LiyanError, match="between 16 and 160"):
        Topic3Service._validate_idempotency_key("short")


def replace_context(
    context: TenantContext,
    *,
    subject_ref: str,
    scopes: frozenset[str],
) -> TenantContext:
    return TenantContext(
        tenant_id=context.tenant_id,
        subject_ref=subject_ref,
        roles=context.roles,
        scopes=scopes,
        trace_id=context.trace_id,
        session_id=context.session_id,
    )
