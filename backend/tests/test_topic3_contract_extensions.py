from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.topic3 import (
    AgentTaskState,
    CodeSandboxContentV1,
    ExtensionContentV1,
    MindMapContentV1,
    Topic3AgentTaskSnapshotV1,
    Topic3ExecutionBlueprintV1,
)
from liyans_contracts.topic3 import (
    TesterContentV1 as QuizContentV1,
)
from pydantic import ValidationError
from topic3_support import generation_command, graph_snapshot, personalization_context

from liyans.domains.topic3.blueprint import ImmutableBlueprintPlanner


def test_generation_command_rejects_duplicate_targets_and_resources() -> None:
    command = generation_command()
    with pytest.raises(ValidationError, match="target_kp_ids"):
        command.model_copy(update={"target_kp_ids": ["KP_ATC_C", "KP_ATC_C"]})
        generation_command(target_kp_ids=["KP_ATC_C", "KP_ATC_C"])
    with pytest.raises(ValidationError, match="requested_resources"):
        generation_command(
            resources=[ResourceType.MIND_MAP, ResourceType.MIND_MAP],
        )


def test_blueprint_contract_rejects_hash_dependency_and_agent_mismatch() -> None:
    graph = graph_snapshot()
    context = personalization_context(graph)
    blueprint = ImmutableBlueprintPlanner().build(generation_command(), graph, context).blueprint
    with pytest.raises(ValidationError, match="blueprint_sha256"):
        Topic3ExecutionBlueprintV1.model_validate(
            {**blueprint.model_dump(mode="json"), "blueprint_sha256": "0" * 64}
        )

    document = blueprint.model_dump(mode="json")
    steps = document["steps"]
    steps[0]["resource_type"] = ResourceType.GRADIENT_QUIZ.value
    document["blueprint_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="not owned"):
        Topic3ExecutionBlueprintV1.model_validate(document)


def test_task_snapshot_requires_success_candidate_and_failure_error() -> None:
    common = {
        "schema_version": "topic3.agent-task-snapshot.v1",
        "task_id": uuid4(),
        "task_version": 1,
        "blueprint_id": uuid4(),
        "blueprint_version": "blueprint-v1",
        "agent": SourceAgent.LECTURER,
        "resource_type": ResourceType.LECTURER_DOC,
        "attempt": 1,
        "max_attempts": 3,
        "request_sha256": "a" * 64,
    }
    with pytest.raises(ValidationError, match="successful"):
        Topic3AgentTaskSnapshotV1(**common, state=AgentTaskState.SUCCEEDED)
    with pytest.raises(ValidationError, match="error_code"):
        Topic3AgentTaskSnapshotV1(**common, state=AgentTaskState.FAILED)


def test_mindmap_quiz_code_and_extension_structural_guards() -> None:
    with pytest.raises(ValidationError, match="unsafe Mermaid"):
        MindMapContentV1(
            schema_version="topic3.mindmap-content.v1",
            direction="TD",
            nodes=[
                {
                    "node_id": "K0",
                    "kp_id": "KP_ATC_C",
                    "label": "Stability",
                    "mastery": 0.5,
                    "state": "CURRENT",
                }
            ],
            edges=[],
            mermaid="graph TD\nclick K0 javascript:alert(1)",
        )
    with pytest.raises(ValidationError, match="sum"):
        QuizContentV1(
            schema_version="topic3.tester-content.v1",
            title="Quiz",
            total_score=10,
            questions=[
                {
                    "question_id": "q1",
                    "question_type": "CONCEPT",
                    "difficulty": 0.5,
                    "target_kp_ids": ["KP_ATC_C"],
                    "prompt_markdown": "Question",
                    "standard_answer": "Answer",
                    "solution_steps": ["Step"],
                    "score": 5,
                }
            ],
            diagnostic_dimensions=["mastery"],
        )
    with pytest.raises(ValidationError, match="exactly one"):
        CodeSandboxContentV1(
            schema_version="topic3.code-sandbox-content.v1",
            title="Simulation",
            objective="Test",
            files=[
                {
                    "path": "a.py",
                    "language": "python",
                    "content": "print(1)",
                    "entrypoint": False,
                }
            ],
            expected_observations=["Output"],
            result_analysis="Analysis",
        )
    with pytest.raises(ValidationError, match="recommended_sequence"):
        ExtensionContentV1(
            schema_version="topic3.extension-content.v1",
            title="Extensions",
            resources=[
                {
                    "resource_id": "r1",
                    "resource_kind": "RESEARCH",
                    "title": "Resource",
                    "summary": "Summary",
                    "relevance_to_kp_ids": ["KP_ATC_C"],
                    "citation_text": "Citation",
                }
            ],
            recommended_sequence=["missing"],
        )


def test_blueprint_hash_can_be_recomputed_from_json_document() -> None:
    graph = graph_snapshot()
    context = personalization_context(graph)
    blueprint = ImmutableBlueprintPlanner().build(generation_command(), graph, context).blueprint
    document = blueprint.model_dump(mode="json", exclude={"blueprint_sha256"})
    assert canonical_sha256(document) == blueprint.blueprint_sha256
    assert blueprint.created_at == datetime(2026, 7, 16, 8, tzinfo=UTC)
