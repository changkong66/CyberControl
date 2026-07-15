from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.topic1 import Topic1GraphSnapshotV1
from liyans_contracts.topic2 import Topic2AgentContextV1
from liyans_contracts.topic3 import (
    LecturerDepth,
    Topic3BlueprintStepV1,
    Topic3ExecutionBlueprintV1,
    Topic3GenerationCommandV1,
)

from liyans.core.errors import ContractError

BLUEPRINT_VERSION = "topic3-blueprint-v1"
ACTIVATION_POLICY_VERSION = "topic3-activation-v1"

AGENT_BY_RESOURCE: dict[ResourceType, SourceAgent] = {
    ResourceType.LECTURER_DOC: SourceAgent.LECTURER,
    ResourceType.MIND_MAP: SourceAgent.MIND_MAP,
    ResourceType.GRADIENT_QUIZ: SourceAgent.TESTER,
    ResourceType.SIMULATION_CODE: SourceAgent.CODE_SANDBOX,
    ResourceType.EXTENSION_MATERIAL: SourceAgent.EXTENSION,
}

PROVIDER_BY_AGENT: dict[SourceAgent, str] = {
    SourceAgent.LECTURER: "spark_text",
    SourceAgent.MIND_MAP: "local",
    SourceAgent.TESTER: "spark_text",
    SourceAgent.CODE_SANDBOX: "xfyun_code",
    SourceAgent.EXTENSION: "spark_text",
}

PROMPT_VERSION_BY_AGENT: dict[SourceAgent, str] = {
    SourceAgent.LECTURER: "lecturer-prompt-v1",
    SourceAgent.MIND_MAP: "mindmap-deterministic-v1",
    SourceAgent.TESTER: "tester-prompt-v1",
    SourceAgent.CODE_SANDBOX: "code-sandbox-prompt-v1",
    SourceAgent.EXTENSION: "extension-prompt-v1",
}

TIMEOUT_BY_AGENT: dict[SourceAgent, float] = {
    SourceAgent.LECTURER: 60.0,
    SourceAgent.MIND_MAP: 10.0,
    SourceAgent.TESTER: 60.0,
    SourceAgent.CODE_SANDBOX: 90.0,
    SourceAgent.EXTENSION: 60.0,
}


@dataclass(frozen=True, slots=True)
class BlueprintDecision:
    blueprint: Topic3ExecutionBlueprintV1
    activation_document: dict[str, object]


class ImmutableBlueprintPlanner:
    """Build a deterministic DAG from exact Topic 1 and Topic 2 snapshots."""

    def build(
        self,
        command: Topic3GenerationCommandV1,
        graph: Topic1GraphSnapshotV1,
        personalization: Topic2AgentContextV1,
    ) -> BlueprintDecision:
        self._validate_bindings(command, graph, personalization)
        resource_order = {
            ResourceType.LECTURER_DOC: 0,
            ResourceType.MIND_MAP: 1,
            ResourceType.GRADIENT_QUIZ: 2,
            ResourceType.SIMULATION_CODE: 3,
            ResourceType.EXTENSION_MATERIAL: 4,
        }
        ordered_resources = sorted(command.requested_resources, key=resource_order.__getitem__)
        agents = [AGENT_BY_RESOURCE[resource] for resource in ordered_resources]
        lecturer_task_id = (
            uuid5(command.operation_id, f"topic3-task:{SourceAgent.LECTURER.value}")
            if SourceAgent.LECTURER in agents
            else None
        )
        activation = self._activation_signals(command, personalization)
        steps: list[Topic3BlueprintStepV1] = []
        for ordinal, resource in enumerate(ordered_resources):
            agent = AGENT_BY_RESOURCE[resource]
            task_id = uuid5(command.operation_id, f"topic3-task:{agent.value}")
            dependencies: list[UUID] = []
            if lecturer_task_id is not None and agent in {
                SourceAgent.TESTER,
                SourceAgent.CODE_SANDBOX,
                SourceAgent.EXTENSION,
            }:
                dependencies.append(lecturer_task_id)
            reasons = ["explicit-resource-request", *activation[agent.value]]
            steps.append(
                Topic3BlueprintStepV1(
                    schema_version="topic3.blueprint-step.v1",
                    task_id=task_id,
                    ordinal=ordinal,
                    agent=agent,
                    resource_type=resource,
                    dependency_task_ids=dependencies,
                    provider_alias=PROVIDER_BY_AGENT[agent],
                    prompt_bundle_version=PROMPT_VERSION_BY_AGENT[agent],
                    timeout_seconds=TIMEOUT_BY_AGENT[agent],
                    max_attempts=3,
                    activation_reasons=reasons,
                )
            )

        blueprint_id = uuid5(command.operation_id, "topic3-blueprint")
        unvalidated = Topic3ExecutionBlueprintV1.model_construct(
            schema_version="topic3.execution-blueprint.v1",
            blueprint_id=blueprint_id,
            blueprint_version=BLUEPRINT_VERSION,
            generation_session_id=command.generation_session_id,
            generation_session_version=1,
            topic1_graph_snapshot_id=graph.snapshot_id,
            topic1_graph_version=graph.graph_version,
            topic1_graph_sha256=graph.content_sha256,
            topic2_profile_id=personalization.profile.profile_id,
            topic2_profile_version=personalization.profile.profile_version,
            topic2_path_snapshot_id=personalization.learning_path.snapshot.path_snapshot_id,
            topic2_path_version=personalization.learning_path.snapshot.path_version,
            personalization_policy_digest=personalization.personalization_policy_digest,
            target_kp_ids=command.target_kp_ids,
            max_parallelism=min(command.max_parallelism, len(steps)),
            allow_partial=command.allow_partial,
            activation_policy_version=ACTIVATION_POLICY_VERSION,
            steps=steps,
            blueprint_sha256="0" * 64,
            created_at=command.requested_at,
        )
        document = unvalidated.model_dump(mode="json", exclude={"blueprint_sha256"})
        blueprint = Topic3ExecutionBlueprintV1(
            **document,
            blueprint_sha256=canonical_sha256(document),
        )
        return BlueprintDecision(
            blueprint=blueprint,
            activation_document={
                "policy_version": ACTIVATION_POLICY_VERSION,
                "signals": activation,
                "requested_resources": [value.value for value in command.requested_resources],
                "selected_agents": [value.value for value in agents],
                "max_parallelism": blueprint.max_parallelism,
                "allow_partial": blueprint.allow_partial,
            },
        )

    @staticmethod
    def _validate_bindings(
        command: Topic3GenerationCommandV1,
        graph: Topic1GraphSnapshotV1,
        personalization: Topic2AgentContextV1,
    ) -> None:
        if graph.course_id != command.course_id:
            raise ContractError("The Topic 1 graph does not match the requested course.")
        if (
            personalization.course_id != command.course_id
            or personalization.learner_ref != command.learner_ref
        ):
            raise ContractError("The Topic 2 context does not match the requested learner course.")
        active_ids = {
            point.kp_id
            for point in graph.content.knowledge_points
            if point.status.value == "ACTIVE"
        }
        unknown = sorted(set(command.target_kp_ids) - active_ids)
        if unknown:
            raise ContractError(
                "The generation request references unavailable knowledge points.",
                details={"unknown_kp_ids": unknown[:32]},
            )

    @staticmethod
    def _activation_signals(
        command: Topic3GenerationCommandV1,
        context: Topic2AgentContextV1,
    ) -> dict[str, list[str]]:
        profile = context.profile
        target_set = set(command.target_kp_ids)
        target_memory = [item for item in context.memory_states if item.kp_id in target_set]
        high_memory_risk = any(
            item.risk_level.value in {"HIGH", "CRITICAL"} for item in target_memory
        )
        low_retrievability = any(item.retrievability < 0.6 for item in target_memory)
        signals: dict[str, list[str]] = {agent.value: [] for agent in SourceAgent}
        if profile.knowledge_mastery < 0.6:
            signals[SourceAgent.LECTURER.value].append("low-knowledge-mastery")
            signals[SourceAgent.TESTER.value].append("diagnose-mastery-deficit")
        if high_memory_risk or low_retrievability:
            signals[SourceAgent.LECTURER.value].append("memory-reinforcement-required")
            signals[SourceAgent.TESTER.value].append("retrieval-practice-required")
            signals[SourceAgent.MIND_MAP.value].append("highlight-memory-risk")
        if profile.misconception_preference >= 0.5:
            signals[SourceAgent.LECTURER.value].append("misconception-remediation")
            signals[SourceAgent.TESTER.value].append("misconception-diagnostics")
        if command.lecturer_depth == LecturerDepth.ENGINEERING:
            signals[SourceAgent.CODE_SANDBOX.value].append("engineering-depth-selected")
            signals[SourceAgent.EXTENSION.value].append("industry-extension-selected")
        if profile.learning_goal_tendency >= 0.65:
            signals[SourceAgent.EXTENSION.value].append("advanced-goal-tendency")
        if profile.learning_pace < 0.4:
            signals[SourceAgent.LECTURER.value].append("slower-pacing")
        return signals
