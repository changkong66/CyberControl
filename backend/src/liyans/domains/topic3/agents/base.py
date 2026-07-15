from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar
from uuid import UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.providers import LiteToolDefinitionV1, ResponsesLiteRequestV1
from liyans_contracts.topic1 import Topic1GraphSnapshotV1
from liyans_contracts.topic2 import Topic2AgentContextV1
from liyans_contracts.topic3 import (
    BlockStatus,
    BlockType,
    BlockV1,
    CandidateProvenanceV1,
    CandidateStatus,
    CandidateV1,
    Topic3BlueprintStepV1,
    Topic3ExecutionBlueprintV1,
    Topic3GenerationCommandV1,
)
from pydantic import BaseModel, ValidationError

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.providers.topic3 import ProviderExecutionResult, Topic3ProviderRegistry

ContentT = TypeVar("ContentT", bound=BaseModel)
PROVIDER_IDENTITY_FIELDS = frozenset(
    {
        "audit_event_id",
        "change_id",
        "created_by_subject",
        "generation_session_id",
        "learner_ref",
        "memory_state_id",
        "operation_id",
        "parent_memory_state_id",
        "parent_path_snapshot_id",
        "parent_profile_id",
        "path_snapshot_id",
        "profile_id",
        "source_event_id",
        "to_path_snapshot_id",
        "from_path_snapshot_id",
    }
)


@dataclass(frozen=True, slots=True)
class AgentExecutionContext:
    command: Topic3GenerationCommandV1
    graph: Topic1GraphSnapshotV1
    personalization: Topic2AgentContextV1
    blueprint: Topic3ExecutionBlueprintV1
    step: Topic3BlueprintStepV1
    attempt: int
    dependency_candidates: tuple[CandidateV1, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentExecutionOutcome:
    candidate: CandidateV1
    provider_result: ProviderExecutionResult | None
    provider_request: ResponsesLiteRequestV1 | None


class AgentExecutionFailure(RuntimeError):
    def __init__(
        self,
        request: ResponsesLiteRequestV1,
        provider_model_alias: str,
        started_at: datetime,
        completed_at: datetime,
        cause: Exception,
        provider_result: ProviderExecutionResult | None = None,
    ) -> None:
        super().__init__("Topic 3 Agent execution failed")
        self.request = request
        self.provider_model_alias = provider_model_alias
        self.started_at = started_at
        self.completed_at = completed_at
        self.cause = cause
        self.provider_result = provider_result


class Topic3Agent(ABC):
    source_agent: SourceAgent
    resource_type: ResourceType

    @abstractmethod
    async def execute(self, context: AgentExecutionContext) -> AgentExecutionOutcome: ...


class ProviderBackedAgent(Topic3Agent, Generic[ContentT]):
    content_model: type[ContentT]
    block_type: BlockType
    content_schema_version: str
    build_version = "topic3-agent-v1"
    max_output_tokens = 8192

    def __init__(self, providers: Topic3ProviderRegistry) -> None:
        self._providers = providers

    async def execute(self, context: AgentExecutionContext) -> AgentExecutionOutcome:
        request = self._build_request(context)
        provider = self._providers.require(context.step.provider_alias)
        started_at = datetime.now(UTC)
        try:
            result = await provider.execute(request)
        except Exception as exc:
            raise AgentExecutionFailure(
                request=request,
                provider_model_alias=provider.model_alias,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                cause=exc,
            ) from exc
        try:
            content = self.content_model.model_validate(result.structured_output)
            self.validate_content(content, context)
            blocks = self.to_blocks(content, context)
        except ValidationError as exc:
            error = LiyanError(
                ErrorCode.TOPIC3_AGENT_OUTPUT_INVALID,
                "The approved provider returned an invalid structured Agent result.",
                category=ErrorCategory.PROVIDER,
                retriable=False,
                status_code=502,
                details={"agent": self.source_agent.value, "errors": exc.error_count()},
            )
            raise AgentExecutionFailure(
                request=request,
                provider_model_alias=provider.model_alias,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                cause=error,
                provider_result=result,
            ) from exc
        except LiyanError as exc:
            raise AgentExecutionFailure(
                request=request,
                provider_model_alias=provider.model_alias,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                cause=exc,
                provider_result=result,
            ) from exc
        return AgentExecutionOutcome(
            candidate=self._candidate(
                context,
                blocks,
                provider_alias=context.step.provider_alias,
                provider_request_ids=[result.request_id],
            ),
            provider_result=result,
            provider_request=request,
        )

    def _build_request(self, context: AgentExecutionContext) -> ResponsesLiteRequestV1:
        provider = self._providers.require(context.step.provider_alias)
        return ResponsesLiteRequestV1(
            schema_version="responses.lite.request.v1",
            request_id=uuid5(
                context.step.task_id,
                f"provider-request:{context.attempt}",
            ),
            provider_alias=context.step.provider_alias,
            model_alias=provider.model_alias,
            instructions=self.prompt_instructions(context),
            tools=[
                LiteToolDefinitionV1(
                    name=f"submit_{self.source_agent.value.lower()}_result",
                    description=(
                        "Submit the complete result exactly once using the required JSON schema."
                    ),
                    input_schema=self.content_model.model_json_schema(),
                )
            ],
            input_segments=self.input_segments(context),
            response_schema=self.content_model.model_json_schema(),
            temperature=0.2,
            max_output_tokens=self.max_output_tokens,
            timeout_ms=int(context.step.timeout_seconds * 1000),
        )

    @abstractmethod
    def prompt_instructions(self, context: AgentExecutionContext) -> list[dict[str, Any]]: ...

    def input_segments(self, context: AgentExecutionContext) -> list[dict[str, Any]]:
        target_ids = set(context.command.target_kp_ids)
        profile = context.personalization.profile
        path = context.personalization.learning_path
        knowledge_points = [
            point.model_dump(mode="json")
            for point in context.graph.content.knowledge_points
            if point.kp_id in target_ids
        ]
        prerequisites = [
            edge.model_dump(mode="json")
            for edge in context.graph.content.prerequisites
            if edge.prerequisite_kp_id in target_ids or edge.dependent_kp_id in target_ids
        ]
        misconceptions = [
            item.model_dump(mode="json")
            for item in context.graph.content.misconceptions
            if item.kp_id in target_ids
        ]
        golden_questions = [
            item.model_dump(mode="json")
            for item in context.graph.content.golden_questions
            if item.primary_kp_id in target_ids
        ]
        dependency_summaries = [
            {
                "resource_type": candidate.resource_type.value,
                "blocks": [
                    {
                        "title": block.title,
                        "content_schema_version": block.content_schema_version,
                        "content": block.content,
                    }
                    for block in candidate.blocks
                ],
            }
            for candidate in context.dependency_candidates
        ]
        return [
            {
                "segment_type": "authoritative_topic1",
                "snapshot_version": context.graph.graph_version,
                "knowledge_points": knowledge_points,
                "prerequisites": prerequisites,
                "misconceptions": misconceptions,
                "golden_questions": golden_questions,
            },
            {
                "segment_type": "personalization_topic2",
                "profile": {
                    "profile_version": profile.profile_version,
                    "policy_version": profile.policy_version,
                    "knowledge_mastery": profile.knowledge_mastery,
                    "problem_solving_proficiency": profile.problem_solving_proficiency,
                    "misconception_preference": profile.misconception_preference,
                    "learning_pace": profile.learning_pace,
                    "forgetting_rate": profile.forgetting_rate,
                    "learning_goal_tendency": profile.learning_goal_tendency,
                    "confidence_score": profile.confidence_score,
                    "activity_count": profile.activity_count,
                    "profile_document": self._provider_safe_document(profile.profile_document),
                },
                "memory_states": [
                    {
                        "kp_id": item.kp_id,
                        "state_version": item.state_version,
                        "model_version": item.model_version,
                        "stability_days": item.stability_days,
                        "effective_stability_days": item.effective_stability_days,
                        "elapsed_days": item.elapsed_days,
                        "retrievability": item.retrievability,
                        "forgetting_rate": item.forgetting_rate,
                        "difficulty_factor": item.difficulty_factor,
                        "review_gain": item.review_gain,
                        "review_count": item.review_count,
                        "lapse_count": item.lapse_count,
                        "next_review_at": item.next_review_at.isoformat(),
                        "risk_level": item.risk_level.value,
                        "model_parameters": self._provider_safe_document(item.model_parameters),
                    }
                    for item in context.personalization.memory_states
                    if item.kp_id in target_ids
                ],
                "learning_path": {
                    "path_version": path.snapshot.path_version,
                    "plan_type": path.snapshot.plan_type.value,
                    "trigger_reason": path.snapshot.trigger_reason,
                    "target_goal": path.snapshot.target_goal,
                    "policy_version": path.snapshot.policy_version,
                    "path_document": self._provider_safe_document(path.snapshot.path_document),
                    "decision_document": self._provider_safe_document(
                        path.snapshot.decision_document
                    ),
                    "node_count": path.snapshot.node_count,
                    "estimated_minutes": path.snapshot.estimated_minutes,
                    "manual_override": path.snapshot.manual_override,
                    "change_type": path.change.change_type.value,
                    "change_reason": path.change.reason,
                    "change_document": self._provider_safe_document(path.change.change_document),
                },
            },
            {
                "segment_type": "generation_command",
                "command": {
                    "target_kp_ids": context.command.target_kp_ids,
                    "requested_resources": [
                        value.value for value in context.command.requested_resources
                    ],
                    "lecturer_depth": context.command.lecturer_depth.value,
                    "learning_goal": context.command.learning_goal,
                    "locale": context.command.locale,
                    "allow_partial": context.command.allow_partial,
                },
                "activation_reasons": context.step.activation_reasons,
            },
            {
                "segment_type": "dependency_candidates",
                "candidates": dependency_summaries,
            },
        ]

    @classmethod
    def _provider_safe_document(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: cls._provider_safe_document(item)
                for key, item in value.items()
                if key not in PROVIDER_IDENTITY_FIELDS
            }
        if isinstance(value, list):
            return [cls._provider_safe_document(item) for item in value]
        return value

    def validate_content(self, content: ContentT, context: AgentExecutionContext) -> None:
        del content, context

    def to_blocks(
        self,
        content: ContentT,
        context: AgentExecutionContext,
    ) -> list[BlockV1]:
        document = content.model_dump(mode="json")
        return [
            self.make_block(
                block_id=f"{self.source_agent.value.lower()}-result",
                block_type=self.block_type,
                ordinal=0,
                title=document.get("title"),
                content_schema_version=self.content_schema_version,
                content=document,
                created_at=context.command.requested_at,
            )
        ]

    @staticmethod
    def make_block(
        *,
        block_id: str,
        block_type: BlockType,
        ordinal: int,
        title: str | None,
        content_schema_version: str,
        content: dict[str, Any],
        dependency_block_ids: list[str] | None = None,
        created_at: datetime | None = None,
    ) -> BlockV1:
        return BlockV1(
            schema_version="topic3.block.v1",
            block_id=block_id,
            block_type=block_type,
            ordinal=ordinal,
            title=title,
            content_schema_version=content_schema_version,
            content=content,
            content_sha256=canonical_sha256(content),
            dependency_block_ids=dependency_block_ids or [],
            status=BlockStatus.COMPLETE,
            created_at=created_at or datetime.now(UTC),
        )

    def _candidate(
        self,
        context: AgentExecutionContext,
        blocks: list[BlockV1],
        *,
        provider_alias: str,
        provider_request_ids: list[str],
    ) -> CandidateV1:
        candidate_id = uuid5_for_task(context.step.task_id, "candidate")
        unvalidated = CandidateV1.model_construct(
            schema_version="topic3.candidate.v1",
            candidate_id=candidate_id,
            candidate_version=1,
            parent_candidate_version=None,
            blueprint_id=context.blueprint.blueprint_id,
            blueprint_version=context.blueprint.blueprint_version,
            blueprint_sha256=context.blueprint.blueprint_sha256,
            resource_type=self.resource_type,
            status=CandidateStatus.COMPLETE,
            blocks=blocks,
            provenance=CandidateProvenanceV1(
                agent=self.source_agent,
                agent_build_version=self.build_version,
                prompt_bundle_version=context.step.prompt_bundle_version,
                provider_alias=provider_alias,
                provider_request_ids=provider_request_ids,
            ),
            personalization_policy_digest=(context.personalization.personalization_policy_digest),
            candidate_sha256="0" * 64,
            created_at=context.command.requested_at,
        )
        document = unvalidated.model_dump(mode="json", exclude={"candidate_sha256"})
        return CandidateV1(
            **document,
            candidate_sha256=canonical_sha256(document),
        )


def uuid5_for_task(task_id: UUID, name: str) -> UUID:
    return uuid5(task_id, name)
