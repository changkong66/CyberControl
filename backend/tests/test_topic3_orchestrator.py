from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.providers import LiteToolDefinitionV1, ResponsesLiteRequestV1
from liyans_contracts.topic3 import (
    AgentTaskState,
    BlockStatus,
    BlockType,
    BlockV1,
    CandidateProvenanceV1,
    CandidateStatus,
    CandidateV1,
)
from topic3_support import NOW, generation_command, graph_snapshot, personalization_context

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.domains.topic3.agents import (
    AgentExecutionFailure,
    AgentExecutionOutcome,
)
from liyans.domains.topic3.blueprint import ImmutableBlueprintPlanner
from liyans.domains.topic3.entities import AgentTaskRecord
from liyans.domains.topic3.orchestrator import Topic3Orchestrator
from liyans.domains.topic3.service import Topic3Service


class FakeService:
    def __init__(self) -> None:
        self.latest: dict[UUID, AgentTaskRecord] = {}
        self.invocations: list[object] = []

    async def mark_task_running(self, current: AgentTaskRecord) -> AgentTaskRecord:
        result = replace(
            current,
            task_record_id=uuid5(current.task_id, f"v{current.task_version + 1}"),
            task_version=current.task_version + 1,
            state=AgentTaskState.RUNNING,
            attempt=current.attempt + 1,
            started_at=NOW,
            error_document={},
        )
        self.latest[current.task_id] = result
        return result

    async def complete_task(
        self,
        current: AgentTaskRecord,
        candidate: CandidateV1,
        chunks,
        invocation,
    ) -> AgentTaskRecord:
        del chunks
        if invocation is not None:
            self.invocations.append(invocation)
        document = {
            "candidate_id": str(candidate.candidate_id),
            "candidate_version": candidate.candidate_version,
        }
        result = replace(
            current,
            task_record_id=uuid5(current.task_id, f"v{current.task_version + 1}"),
            task_version=current.task_version + 1,
            state=AgentTaskState.SUCCEEDED,
            result_document=document,
            result_sha256=canonical_sha256(document),
            completed_at=NOW,
        )
        self.latest[current.task_id] = result
        return result

    async def fail_task(self, current, error, invocation) -> AgentTaskRecord:
        if invocation is not None:
            self.invocations.append(invocation)
        document = {
            "error_code": error.code.value,
            "category": error.category.value,
            "retriable": error.retriable,
            "safe_message": error.safe_message,
        }
        result = replace(
            current,
            task_record_id=uuid5(current.task_id, f"v{current.task_version + 1}"),
            task_version=current.task_version + 1,
            state=AgentTaskState.FAILED,
            error_document=document,
            result_sha256=canonical_sha256(document),
            completed_at=NOW,
        )
        self.latest[current.task_id] = result
        return result

    async def skip_task(self, current, *, reason: str) -> AgentTaskRecord:
        result = replace(
            current,
            task_record_id=uuid5(current.task_id, f"v{current.task_version + 1}"),
            task_version=current.task_version + 1,
            state=AgentTaskState.SKIPPED,
            error_document={"error_code": "DEPENDENCY", "safe_message": reason},
            completed_at=NOW,
        )
        self.latest[current.task_id] = result
        return result


class FakeStream:
    def __init__(self) -> None:
        self.progress: list[tuple[str, str]] = []
        self.published: list[object] = []

    def candidate_chunks(self, candidate: CandidateV1) -> list[object]:
        del candidate
        return []

    async def publish_chunks(self, tenant_id: str, chunks) -> None:
        self.published.append((tenant_id, list(chunks)))

    async def publish_progress(self, tenant_id: str, **payload: Any) -> None:
        self.progress.append((tenant_id, str(payload["state"])))


class FakeAgent:
    def __init__(
        self,
        *,
        fail_once: bool = False,
        fail_always: bool = False,
        delay_seconds: float = 0,
    ) -> None:
        self.fail_once = fail_once
        self.fail_always = fail_always
        self.delay_seconds = delay_seconds
        self.calls = 0

    async def execute(self, context) -> AgentExecutionOutcome:
        self.calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.fail_always or (self.fail_once and self.calls == 1):
            now = datetime.now(UTC)
            request = provider_request(context.step.provider_alias, context.step.task_id)
            raise AgentExecutionFailure(
                request=request,
                provider_model_alias="test-model",
                started_at=now,
                completed_at=now,
                cause=LiyanError(
                    ErrorCode.TOPIC3_PROVIDER_UNAVAILABLE,
                    "Injected provider outage.",
                    category=ErrorCategory.PROVIDER,
                    retriable=not self.fail_always,
                    status_code=503,
                ),
            )
        return AgentExecutionOutcome(
            candidate=candidate_for(context),
            provider_result=None,
            provider_request=None,
        )


class FakeAgentRegistry:
    def __init__(self, agents: dict[SourceAgent, FakeAgent]) -> None:
        self.agents = agents

    def require(self, agent: SourceAgent) -> FakeAgent:
        return self.agents[agent]


def provider_request(alias: str, task_id: UUID) -> ResponsesLiteRequestV1:
    return ResponsesLiteRequestV1(
        schema_version="responses.lite.request.v1",
        request_id=uuid5(task_id, "provider-request"),
        provider_alias=alias,
        model_alias="test-model",
        instructions=[{"instruction": "test"}],
        tools=[
            LiteToolDefinitionV1(
                name="submit",
                description="Submit result.",
                input_schema={"type": "object"},
            )
        ],
        input_segments=[{"value": 1}],
        response_schema={"type": "object"},
        temperature=0,
        max_output_tokens=128,
        timeout_ms=5000,
    )


def candidate_for(context) -> CandidateV1:
    content = {"agent": context.step.agent.value, "attempt": context.attempt}
    block = BlockV1(
        schema_version="topic3.block.v1",
        block_id=f"{context.step.agent.value}-block",
        block_type=BlockType.METADATA,
        ordinal=0,
        content_schema_version="topic3.test-content.v1",
        content=content,
        content_sha256=canonical_sha256(content),
        status=BlockStatus.COMPLETE,
        created_at=NOW,
    )
    unvalidated = CandidateV1.model_construct(
        schema_version="topic3.candidate.v1",
        candidate_id=uuid5(context.step.task_id, "candidate"),
        candidate_version=1,
        parent_candidate_version=None,
        blueprint_id=context.blueprint.blueprint_id,
        blueprint_version=context.blueprint.blueprint_version,
        blueprint_sha256=context.blueprint.blueprint_sha256,
        resource_type=context.step.resource_type,
        status=CandidateStatus.COMPLETE,
        blocks=[block],
        provenance=CandidateProvenanceV1(
            agent=context.step.agent,
            agent_build_version="test-v1",
            prompt_bundle_version=context.step.prompt_bundle_version,
            provider_alias="local",
        ),
        personalization_policy_digest=context.personalization.personalization_policy_digest,
        candidate_sha256="0" * 64,
        created_at=NOW,
    )
    document = unvalidated.model_dump(mode="json", exclude={"candidate_sha256"})
    return CandidateV1(**document, candidate_sha256=canonical_sha256(document))


def pending_tasks(blueprint, command) -> list[AgentTaskRecord]:
    return [Topic3Service._pending_task(step, blueprint, command, NOW) for step in blueprint.steps]


def orchestrator(service, registry, stream) -> Topic3Orchestrator:
    return Topic3Orchestrator(
        database=None,
        topic1_repository=None,
        topic2_orchestrator=None,
        service=service,
        planner=ImmutableBlueprintPlanner(),
        agents=registry,
        stream=stream,
    )


@pytest.mark.asyncio
async def test_dag_retries_transient_failure_and_respects_dependencies() -> None:
    graph = graph_snapshot()
    personalization = personalization_context(graph)
    command = generation_command(
        resources=[
            ResourceType.LECTURER_DOC,
            ResourceType.MIND_MAP,
            ResourceType.GRADIENT_QUIZ,
        ]
    )
    blueprint = ImmutableBlueprintPlanner().build(command, graph, personalization).blueprint
    service = FakeService()
    agents = {
        SourceAgent.LECTURER: FakeAgent(fail_once=True),
        SourceAgent.MIND_MAP: FakeAgent(),
        SourceAgent.TESTER: FakeAgent(),
    }
    stream = FakeStream()
    context = TenantContext(
        tenant_id="tenant-a",
        subject_ref=command.learner_ref,
        roles=frozenset(),
        scopes=frozenset({"topic3:admin"}),
        trace_id="a" * 32,
    )
    with tenant_scope(context):
        await orchestrator(service, FakeAgentRegistry(agents), stream)._execute_dag(
            command,
            graph,
            personalization,
            blueprint,
            pending_tasks(blueprint, command),
            [],
        )

    assert agents[SourceAgent.LECTURER].calls == 2
    assert agents[SourceAgent.TESTER].calls == 1
    assert all(task.state == AgentTaskState.SUCCEEDED for task in service.latest.values())
    assert any(item.state == "FAILED" for item in service.invocations)
    assert "RUNNING" in {state for _, state in stream.progress}
    assert "SUCCEEDED" in {state for _, state in stream.progress}


@pytest.mark.asyncio
async def test_dag_skips_dependents_after_terminal_upstream_failure() -> None:
    graph = graph_snapshot()
    personalization = personalization_context(graph)
    command = generation_command(resources=[ResourceType.LECTURER_DOC, ResourceType.GRADIENT_QUIZ])
    blueprint = ImmutableBlueprintPlanner().build(command, graph, personalization).blueprint
    service = FakeService()
    agents = {
        SourceAgent.LECTURER: FakeAgent(fail_always=True),
        SourceAgent.TESTER: FakeAgent(),
    }
    context = TenantContext(
        tenant_id="tenant-a",
        subject_ref=command.learner_ref,
        roles=frozenset(),
        scopes=frozenset({"topic3:admin"}),
        trace_id="a" * 32,
    )
    with tenant_scope(context):
        await orchestrator(service, FakeAgentRegistry(agents), FakeStream())._execute_dag(
            command,
            graph,
            personalization,
            blueprint,
            pending_tasks(blueprint, command),
            [],
        )

    states = {task.agent: task.state for task in service.latest.values()}
    assert states[SourceAgent.LECTURER] == AgentTaskState.FAILED
    assert states[SourceAgent.TESTER] == AgentTaskState.SKIPPED
    assert agents[SourceAgent.TESTER].calls == 0


@pytest.mark.asyncio
async def test_dag_enforces_each_blueprint_step_timeout() -> None:
    graph = graph_snapshot()
    personalization = personalization_context(graph)
    command = generation_command(resources=[ResourceType.MIND_MAP])
    blueprint = ImmutableBlueprintPlanner().build(command, graph, personalization).blueprint
    step = blueprint.steps[0].model_copy(update={"timeout_seconds": 0.001, "max_attempts": 2})
    blueprint = blueprint.model_copy(update={"steps": [step]})
    service = FakeService()
    agent = FakeAgent(delay_seconds=0.05)
    context = TenantContext(
        tenant_id="tenant-a",
        subject_ref=command.learner_ref,
        roles=frozenset(),
        scopes=frozenset({"topic3:admin"}),
        trace_id="a" * 32,
    )
    with tenant_scope(context):
        await orchestrator(
            service,
            FakeAgentRegistry({SourceAgent.MIND_MAP: agent}),
            FakeStream(),
        )._execute_dag(
            command,
            graph,
            personalization,
            blueprint,
            pending_tasks(blueprint, command),
            [],
        )

    final = service.latest[step.task_id]
    assert agent.calls == 2
    assert final.state == AgentTaskState.FAILED
    assert final.error_document["error_code"] == ErrorCode.TIMEOUT.value


def test_queue_request_preserves_trusted_context_without_credentials() -> None:
    command = generation_command(resources=[ResourceType.MIND_MAP])
    context = TenantContext(
        tenant_id="tenant-a",
        subject_ref=command.learner_ref,
        roles=frozenset({"student"}),
        scopes=frozenset({"topic3:generation:write"}),
        trace_id="b" * 32,
        session_id=command.generation_session_id,
    )
    request = orchestrator(FakeService(), FakeAgentRegistry({}), FakeStream()).queue_request(
        command.generation_session_id,
        context,
    )
    assert request.tenant_id == "tenant-a"
    assert request.payload["subject_ref"] == command.learner_ref
    assert request.payload["session_id"] == str(command.generation_session_id)
    assert "token" not in request.payload
    assert "api_key" not in request.payload
