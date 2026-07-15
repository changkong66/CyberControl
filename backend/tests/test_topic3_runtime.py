from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.providers import ResponsesLiteRequestV1
from liyans_contracts.topic3 import (
    CodeSandboxContentV1,
    ExtensionContentV1,
    LecturerContentV1,
    MindMapContentV1,
)
from liyans_contracts.topic3 import (
    TesterContentV1 as QuizContentV1,
)
from topic3_support import generation_command, graph_snapshot, personalization_context

from liyans.core.errors import ErrorCode, LiyanError
from liyans.core.provider_policy import ProviderPolicyRegistry
from liyans.domains.topic3.agents import AgentExecutionContext, AgentExecutionFailure
from liyans.domains.topic3.agents.code_sandbox import CodeSandboxAgent
from liyans.domains.topic3.agents.extension import ExtensionAgent
from liyans.domains.topic3.agents.lecturer import LecturerAgent
from liyans.domains.topic3.agents.mindmap import MindMapAgent
from liyans.domains.topic3.agents.tester import TesterAgent as QuizAgent
from liyans.domains.topic3.blueprint import ImmutableBlueprintPlanner
from liyans.domains.topic3.streaming import Topic3StreamCoordinator
from liyans.infrastructure.streaming.sse import InMemorySSEReplayLog, SSEBroker
from liyans.providers.topic3 import ProviderExecutionResult, Topic3ProviderRegistry


@dataclass
class StaticProvider:
    alias: str
    model_alias: str
    output: dict[str, Any]
    calls: list[ResponsesLiteRequestV1]

    async def execute(self, request: ResponsesLiteRequestV1) -> ProviderExecutionResult:
        self.calls.append(request)
        now = datetime.now(UTC)
        return ProviderExecutionResult(
            request_id=str(request.request_id),
            structured_output=self.output,
            input_tokens=120,
            output_tokens=240,
            started_at=now,
            completed_at=now,
        )

    async def close(self) -> None:
        return None


def provider_registry(provider: StaticProvider) -> Topic3ProviderRegistry:
    policy = ProviderPolicyRegistry.load(
        Path(__file__).resolve().parents[2] / "config" / "providers.toml"
    )
    return Topic3ProviderRegistry(policy, {provider.alias: provider})


def execution_context(resource: ResourceType, *, attempt: int = 1) -> AgentExecutionContext:
    graph = graph_snapshot()
    personalization = personalization_context(graph)
    command = generation_command(resources=[resource])
    blueprint = ImmutableBlueprintPlanner().build(command, graph, personalization).blueprint
    return AgentExecutionContext(
        command=command,
        graph=graph,
        personalization=personalization,
        blueprint=blueprint,
        step=blueprint.steps[0],
        attempt=attempt,
    )


def test_blueprint_is_deterministic_topological_and_personalized() -> None:
    graph = graph_snapshot()
    personalization = personalization_context(graph)
    command = generation_command(
        resources=[
            ResourceType.GRADIENT_QUIZ,
            ResourceType.EXTENSION_MATERIAL,
            ResourceType.LECTURER_DOC,
            ResourceType.MIND_MAP,
            ResourceType.SIMULATION_CODE,
        ]
    )
    planner = ImmutableBlueprintPlanner()
    first = planner.build(command, graph, personalization)
    second = planner.build(command, graph, personalization)

    assert first == second
    assert first.blueprint.blueprint_sha256 == second.blueprint.blueprint_sha256
    assert [step.agent for step in first.blueprint.steps] == [
        SourceAgent.LECTURER,
        SourceAgent.MIND_MAP,
        SourceAgent.TESTER,
        SourceAgent.CODE_SANDBOX,
        SourceAgent.EXTENSION,
    ]
    lecturer_id = first.blueprint.steps[0].task_id
    assert first.blueprint.steps[1].dependency_task_ids == []
    assert all(step.dependency_task_ids == [lecturer_id] for step in first.blueprint.steps[2:])
    assert "memory-reinforcement-required" in first.activation_document["signals"]["Lecturer"]
    assert first.blueprint.max_parallelism == 3


def test_blueprint_rejects_unknown_target_and_mixed_course() -> None:
    graph = graph_snapshot()
    context = personalization_context(graph)
    planner = ImmutableBlueprintPlanner()
    with pytest.raises(LiyanError) as unknown:
        planner.build(
            generation_command(target_kp_ids=["KP_ATC_UNKNOWN"]),
            graph,
            context,
        )
    assert unknown.value.code == ErrorCode.CONTRACT_INVALID

    wrong = generation_command().model_copy(update={"course_id": "CRS_OTHER_001"})
    with pytest.raises(LiyanError, match="graph"):
        planner.build(wrong, graph, context)


@pytest.mark.asyncio
async def test_lecturer_agent_builds_responses_lite_and_candidate() -> None:
    output = LecturerContentV1(
        schema_version="topic3.lecturer-content.v1",
        title="Closed-loop stability",
        learning_objectives=["Explain stability conditions."],
        sections=[
            {
                "section_id": "stability-core",
                "title": "Core explanation",
                "depth": "ENGINEERING",
                "markdown": "Use the characteristic equation from the authoritative context.",
                "target_kp_ids": ["KP_ATC_C"],
            }
        ],
        summary=["Stability is evaluated from the closed-loop characteristic equation."],
        misconception_alerts=["Do not reverse the feedback sign."],
        personalization_notes=["Reinforce the high-risk memory state."],
    ).model_dump(mode="json")
    provider = StaticProvider("spark_text", "spark-test", output, [])
    agent = LecturerAgent(provider_registry(provider))
    outcome = await agent.execute(execution_context(ResourceType.LECTURER_DOC))

    assert outcome.candidate.resource_type == ResourceType.LECTURER_DOC
    assert outcome.candidate.provenance.agent == SourceAgent.LECTURER
    assert outcome.candidate.blocks[0].content_schema_version == "topic3.lecturer-content.v1"
    assert provider.calls[0].instructions
    assert provider.calls[0].tools
    assert provider.calls[0].request_id == outcome.provider_request.request_id
    assert provider.calls[0].input_segments[0]["snapshot_version"] == 3
    provider_input = json.dumps(provider.calls[0].input_segments, sort_keys=True)
    assert all(
        value not in provider_input
        for value in context_identity_values(execution_context(ResourceType.LECTURER_DOC))
    )


@pytest.mark.asyncio
async def test_tester_code_and_extension_validate_domain_boundaries() -> None:
    tester_output = QuizContentV1(
        schema_version="topic3.tester-content.v1",
        title="Stability diagnostic",
        total_score=10,
        questions=[
            {
                "question_id": "q1",
                "question_type": "CONCEPT",
                "difficulty": 0.6,
                "target_kp_ids": ["KP_ATC_C"],
                "prompt_markdown": "Explain the stability criterion.",
                "standard_answer": "Use the authoritative characteristic equation.",
                "solution_steps": ["Form the characteristic equation.", "Apply the criterion."],
                "score": 10,
            }
        ],
        diagnostic_dimensions=["knowledge_mastery"],
    ).model_dump(mode="json")
    tester_provider = StaticProvider("spark_text", "spark-test", tester_output, [])
    tester = QuizAgent(provider_registry(tester_provider))
    tester_result = await tester.execute(execution_context(ResourceType.GRADIENT_QUIZ))
    assert tester_result.candidate.blocks[0].block_type.value == "QUIZ"

    code_output = CodeSandboxContentV1(
        schema_version="topic3.code-sandbox-content.v1",
        title="Step response simulation",
        objective="Compare stable closed-loop responses.",
        files=[
            {
                "path": "main.py",
                "language": "python",
                "content": "import numpy as np\nt = np.linspace(0, 10, 101)\ny = 1 - np.exp(-t)",
                "entrypoint": True,
            }
        ],
        parameters={"time_horizon": "10 s"},
        expected_observations=["The response converges."],
        result_analysis="A bounded response is observed for this example.",
        safety_notes=["No network or filesystem access."],
    ).model_dump(mode="json")
    code_provider = StaticProvider("xfyun_code", "code-test", code_output, [])
    code = CodeSandboxAgent(provider_registry(code_provider))
    code_result = await code.execute(execution_context(ResourceType.SIMULATION_CODE))
    assert code_result.candidate.blocks[0].block_type.value == "CODE"

    extension_output = ExtensionContentV1(
        schema_version="topic3.extension-content.v1",
        title="Engineering extensions",
        resources=[
            {
                "resource_id": "ext-1",
                "resource_kind": "ENGINEERING",
                "title": "Robustness margin study",
                "summary": "Compare stability margin changes under parameter uncertainty.",
                "relevance_to_kp_ids": ["KP_ATC_C"],
                "citation_text": "Bound to the accepted course authority source.",
            }
        ],
        recommended_sequence=["ext-1"],
    ).model_dump(mode="json")
    extension_provider = StaticProvider("spark_text", "spark-test", extension_output, [])
    extension = ExtensionAgent(provider_registry(extension_provider))
    extension_result = await extension.execute(execution_context(ResourceType.EXTENSION_MATERIAL))
    assert extension_result.candidate.provenance.agent == SourceAgent.EXTENSION


@pytest.mark.asyncio
async def test_agent_rejects_unsafe_code_and_out_of_scope_quiz() -> None:
    unsafe = {
        "schema_version": "topic3.code-sandbox-content.v1",
        "title": "Unsafe",
        "objective": "Rejected code",
        "files": [
            {
                "path": "main.py",
                "language": "python",
                "content": "import os\nos.system('whoami')",
                "entrypoint": True,
            }
        ],
        "parameters": {},
        "expected_observations": ["none"],
        "result_analysis": "none",
        "safety_notes": [],
    }
    provider = StaticProvider("xfyun_code", "code-test", unsafe, [])
    with pytest.raises(AgentExecutionFailure) as raised:
        await CodeSandboxAgent(provider_registry(provider)).execute(
            execution_context(ResourceType.SIMULATION_CODE)
        )
    assert isinstance(raised.value.cause, LiyanError)
    assert raised.value.cause.code == ErrorCode.TOPIC3_AGENT_OUTPUT_INVALID
    assert raised.value.provider_result is not None

    quiz = {
        "schema_version": "topic3.tester-content.v1",
        "title": "Out of scope",
        "total_score": 1,
        "questions": [
            {
                "question_id": "q1",
                "question_type": "CONCEPT",
                "difficulty": 0.5,
                "target_kp_ids": ["KP_ATC_A"],
                "prompt_markdown": "Question",
                "standard_answer": "Answer",
                "solution_steps": ["Step"],
                "score": 1,
            }
        ],
        "diagnostic_dimensions": ["mastery"],
    }
    quiz_provider = StaticProvider("spark_text", "spark-test", quiz, [])
    with pytest.raises(AgentExecutionFailure) as quiz_error:
        await QuizAgent(provider_registry(quiz_provider)).execute(
            execution_context(ResourceType.GRADIENT_QUIZ)
        )
    assert quiz_error.value.cause.code == ErrorCode.TOPIC3_AGENT_OUTPUT_INVALID


@pytest.mark.asyncio
async def test_mindmap_is_deterministic_safe_and_personalized() -> None:
    context = execution_context(ResourceType.MIND_MAP)
    agent = MindMapAgent()
    first = await agent.execute(context)
    second = await agent.execute(context)
    content = MindMapContentV1.model_validate(first.candidate.blocks[0].content)

    assert content.mermaid.startswith("graph TD")
    assert "click " not in content.mermaid.lower()
    assert {node.kp_id for node in content.nodes} == {"KP_ATC_A", "KP_ATC_B", "KP_ATC_C"}
    assert next(node for node in content.nodes if node.kp_id == "KP_ATC_C").state == "CURRENT"
    assert first.candidate.candidate_sha256 == second.candidate.candidate_sha256
    assert first.provider_result is None


@pytest.mark.asyncio
async def test_stream_coordinator_chunks_persists_order_and_publishes() -> None:
    output = LecturerContentV1(
        schema_version="topic3.lecturer-content.v1",
        title="Unicode stability",
        learning_objectives=["Explain stability."],
        sections=[
            {
                "section_id": "unicode",
                "title": "稳定性",
                "depth": "ENGINEERING",
                "markdown": "闭环稳定性" * 200,
                "target_kp_ids": ["KP_ATC_C"],
            }
        ],
        summary=["稳定"],
    ).model_dump(mode="json")
    provider = StaticProvider("spark_text", "spark-test", output, [])
    candidate = (
        await LecturerAgent(provider_registry(provider)).execute(
            execution_context(ResourceType.LECTURER_DOC)
        )
    ).candidate
    replay = InMemorySSEReplayLog(capacity_per_tenant=100)
    coordinator = Topic3StreamCoordinator(SSEBroker(replay), max_chunk_bytes=256)
    first = coordinator.candidate_chunks(candidate)
    second = coordinator.candidate_chunks(candidate)

    assert [chunk.fragment_id for chunk in first] == [chunk.fragment_id for chunk in second]
    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))
    assert all(len(chunk.data.encode("utf-8")) <= 256 for chunk in first)
    await coordinator.publish_chunks("tenant-a", first)
    await coordinator.publish_progress(
        "tenant-a",
        generation_session_id="session",
        task_id="task",
        agent="Lecturer",
        state="SUCCEEDED",
        attempt=1,
    )
    events = await replay.replay("tenant-a", None)
    assert len(events) == len(first) + 1
    assert events[-1].event_type == "topic3.generation.progress"


def context_identity_values(context: AgentExecutionContext) -> set[str]:
    return {
        context.command.learner_ref,
        str(context.command.operation_id),
        str(context.command.generation_session_id),
        str(context.personalization.profile.profile_id),
        str(context.personalization.profile.audit_event_id),
        str(context.personalization.learning_path.snapshot.path_snapshot_id),
        str(context.personalization.learning_path.audit_event_id),
    }
