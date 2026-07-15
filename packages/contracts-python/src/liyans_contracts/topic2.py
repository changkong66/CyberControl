from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from .common import FROZEN_MODEL_CONFIG, Sha256Hex, VersionString, canonical_sha256

MAX_BEHAVIOR_PAYLOAD_BYTES = 64 * 1024


class Topic2ProfileDimension(StrEnum):
    KNOWLEDGE_MASTERY = "KNOWLEDGE_MASTERY"
    PROBLEM_SOLVING_PROFICIENCY = "PROBLEM_SOLVING_PROFICIENCY"
    MISCONCEPTION_PREFERENCE = "MISCONCEPTION_PREFERENCE"
    LEARNING_PACE = "LEARNING_PACE"
    FORGETTING_RATE = "FORGETTING_RATE"
    LEARNING_GOAL_TENDENCY = "LEARNING_GOAL_TENDENCY"


class Topic2BehaviorEventType(StrEnum):
    ANSWER_SUBMITTED = "ANSWER_SUBMITTED"
    RESOURCE_VIEWED = "RESOURCE_VIEWED"
    SIMULATION_RUN = "SIMULATION_RUN"
    REVIEW_COMPLETED = "REVIEW_COMPLETED"
    CODE_EXECUTED = "CODE_EXECUTED"
    SESSION_FOCUSED = "SESSION_FOCUSED"
    GOAL_SELECTED = "GOAL_SELECTED"


class Topic2BehaviorSourceType(StrEnum):
    LEARNER_UI = "LEARNER_UI"
    LECTURER = "LECTURER"
    MINDMAP = "MINDMAP"
    TESTER = "TESTER"
    CODE_SANDBOX = "CODE_SANDBOX"
    EXTENSION = "EXTENSION"
    SYSTEM = "SYSTEM"


class Topic2MemoryRiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Topic2LearningTier(StrEnum):
    FOUNDATION = "FOUNDATION"
    REINFORCEMENT = "REINFORCEMENT"
    EXTENSION = "EXTENSION"


class Topic2PathPlanType(StrEnum):
    INITIAL = "INITIAL"
    REPLANNED = "REPLANNED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    RESTORED = "RESTORED"


class Topic2PathChangeType(StrEnum):
    INITIALIZED = "INITIALIZED"
    MEMORY_RISK = "MEMORY_RISK"
    MASTERY_DEFICIT = "MASTERY_DEFICIT"
    MISCONCEPTION = "MISCONCEPTION"
    GOAL_CHANGED = "GOAL_CHANGED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    TOPOLOGY_REPAIRED = "TOPOLOGY_REPAIRED"
    RESTORED = "RESTORED"


class Topic2OperationCommandV1(BaseModel):
    """Replay-stable command identity for profile, memory, or path generation."""

    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic2.operation-command.v1"] = "topic2.operation-command.v1"
    operation_id: UUID
    requested_at: AwareDatetime


class Topic2BehaviorEventCommandV1(BaseModel):
    """Tokenized learner behavior accepted by the silent profiling pipeline."""

    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic2.behavior-event-command.v1"] = "topic2.behavior-event-command.v1"
    event_id: UUID
    source_event_id: str = Field(min_length=1, max_length=160)
    event_version: int = Field(default=1, ge=1)
    learner_ref: str = Field(min_length=3, max_length=256)
    course_id: str = Field(min_length=3, max_length=64)
    kp_id: str | None = Field(default=None, min_length=6, max_length=120)
    session_id: UUID | None = None
    event_type: Topic2BehaviorEventType
    source_type: Topic2BehaviorSourceType
    duration_seconds: float | None = Field(default=None, ge=0, le=86400)
    response_latency_ms: int | None = Field(default=None, ge=0, le=86400000)
    correctness: float | None = Field(default=None, ge=0, le=1)
    score: float | None = Field(default=None, ge=0, le=1)
    attempt_count: int = Field(default=0, ge=0, le=1000)
    interaction_count: int = Field(default=0, ge=0, le=100000)
    attention_ratio: float | None = Field(default=None, ge=0, le=1)
    misconception_ids: list[str] = Field(default_factory=list, max_length=64)
    goal_tags: list[str] = Field(default_factory=list, max_length=32)
    payload: dict[str, Any]
    payload_sha256: Sha256Hex
    occurred_at: AwareDatetime

    @model_validator(mode="after")
    def validate_payload(self) -> Topic2BehaviorEventCommandV1:
        payload_bytes = json.dumps(
            self.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(payload_bytes) > MAX_BEHAVIOR_PAYLOAD_BYTES:
            raise ValueError(f"behavior payload cannot exceed {MAX_BEHAVIOR_PAYLOAD_BYTES} bytes")
        if canonical_sha256(self.payload) != self.payload_sha256:
            raise ValueError("payload_sha256 does not match payload")
        return self


class Topic2LearningBehaviorEventV1(Topic2BehaviorEventCommandV1):
    """Immutable persisted behavior event with audit provenance."""

    schema_version: Literal["topic2.learning-behavior-event.v1"] = (
        "topic2.learning-behavior-event.v1"
    )
    received_at: AwareDatetime
    audit_event_id: UUID
    created_at: AwareDatetime


class Topic2ProfileFeatureV1(BaseModel):
    """Evidence-backed feature supporting one six-dimensional profile snapshot."""

    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic2.profile-feature.v1"] = "topic2.profile-feature.v1"
    feature_id: UUID
    dimension: Topic2ProfileDimension
    feature_key: str = Field(min_length=1, max_length=160)
    value_document: dict[str, Any]
    normalized_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    evidence_count: int = Field(ge=0)
    source_event_ids: list[str] = Field(default_factory=list, max_length=5000)
    computed_at: AwareDatetime


class Topic2DimensionScoresV1(BaseModel):
    """Normalized six-dimensional learner state used by Topic 3 personalization."""

    model_config = FROZEN_MODEL_CONFIG

    knowledge_mastery: float = Field(ge=0, le=1)
    problem_solving_proficiency: float = Field(ge=0, le=1)
    misconception_preference: float = Field(ge=0, le=1)
    learning_pace: float = Field(ge=0, le=1)
    forgetting_rate: float = Field(ge=0, le=1)
    learning_goal_tendency: float = Field(ge=0, le=1)


class Topic2StudentProfileV1(BaseModel):
    """Immutable profile aggregate, full evidence features, and audit binding."""

    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic2.student-profile.v1"] = "topic2.student-profile.v1"
    profile_id: UUID
    learner_ref: str = Field(min_length=3, max_length=256)
    course_id: str = Field(min_length=3, max_length=64)
    profile_version: int = Field(ge=1)
    parent_profile_id: UUID | None = None
    policy_version: VersionString
    knowledge_mastery: float = Field(ge=0, le=1)
    problem_solving_proficiency: float = Field(ge=0, le=1)
    misconception_preference: float = Field(ge=0, le=1)
    learning_pace: float = Field(ge=0, le=1)
    forgetting_rate: float = Field(ge=0, le=1)
    learning_goal_tendency: float = Field(ge=0, le=1)
    confidence_score: float = Field(ge=0, le=1)
    activity_count: int = Field(ge=0)
    last_event_at: AwareDatetime | None = None
    source_window_start: AwareDatetime | None = None
    source_window_end: AwareDatetime | None = None
    profile_document: dict[str, Any]
    content_sha256: Sha256Hex
    frozen_at: AwareDatetime
    features: list[Topic2ProfileFeatureV1] = Field(min_length=6, max_length=10000)
    audit_event_id: UUID
    created_by_subject: str = Field(min_length=1, max_length=256)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_profile(self) -> Topic2StudentProfileV1:
        if canonical_sha256(self.profile_document) != self.content_sha256:
            raise ValueError("content_sha256 does not match profile_document")
        identity = {
            "profile_id": str(self.profile_id),
            "profile_version": self.profile_version,
            "learner_ref": self.learner_ref,
            "course_id": self.course_id,
            "policy_version": self.policy_version,
        }
        if any(self.profile_document.get(key) != value for key, value in identity.items()):
            raise ValueError("profile_document identity does not match indexed fields")
        dimensions = Topic2DimensionScoresV1(
            knowledge_mastery=self.knowledge_mastery,
            problem_solving_proficiency=self.problem_solving_proficiency,
            misconception_preference=self.misconception_preference,
            learning_pace=self.learning_pace,
            forgetting_rate=self.forgetting_rate,
            learning_goal_tendency=self.learning_goal_tendency,
        ).model_dump(mode="json")
        if self.profile_document.get("dimensions") != dimensions:
            raise ValueError("profile_document dimensions do not match indexed scores")
        aggregate_dimensions = {
            feature.dimension for feature in self.features if feature.feature_key == "aggregate"
        }
        if aggregate_dimensions != set(Topic2ProfileDimension):
            raise ValueError("profile must contain one aggregate feature for all six dimensions")
        if (
            self.source_window_start is not None
            and self.source_window_end is not None
            and self.source_window_end < self.source_window_start
        ):
            raise ValueError("profile source window is reversed")
        return self


class Topic2MemoryStateV1(BaseModel):
    """Versioned exponential-forgetting state for one Topic 1 knowledge point."""

    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic2.memory-state.v1"] = "topic2.memory-state.v1"
    memory_state_id: UUID
    learner_ref: str = Field(min_length=3, max_length=256)
    course_id: str = Field(min_length=3, max_length=64)
    kp_id: str = Field(min_length=6, max_length=120)
    state_version: int = Field(ge=1)
    parent_memory_state_id: UUID | None = None
    model_version: VersionString
    stability_days: float = Field(gt=0, le=36500)
    effective_stability_days: float = Field(gt=0, le=36500)
    elapsed_days: float = Field(ge=0)
    retrievability: float = Field(ge=0, le=1)
    forgetting_rate: float = Field(ge=0, le=1)
    difficulty_factor: float = Field(ge=0.25, le=4)
    review_gain: float = Field(ge=0, le=16)
    review_count: int = Field(ge=0)
    lapse_count: int = Field(ge=0)
    last_reviewed_at: AwareDatetime | None = None
    last_activity_at: AwareDatetime
    next_review_at: AwareDatetime
    risk_level: Topic2MemoryRiskLevel
    model_parameters: dict[str, Any]
    content_sha256: Sha256Hex
    computed_at: AwareDatetime
    audit_event_id: UUID
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_memory(self) -> Topic2MemoryStateV1:
        if self.lapse_count > self.review_count:
            raise ValueError("lapse_count cannot exceed review_count")
        document = {
            "schema_version": self.schema_version,
            "memory_state_id": str(self.memory_state_id),
            "learner_ref": self.learner_ref,
            "course_id": self.course_id,
            "kp_id": self.kp_id,
            "state_version": self.state_version,
            "parent_memory_state_id": (
                None if self.parent_memory_state_id is None else str(self.parent_memory_state_id)
            ),
            "model_version": self.model_version,
            "stability_days": self.stability_days,
            "effective_stability_days": self.effective_stability_days,
            "elapsed_days": self.elapsed_days,
            "retrievability": self.retrievability,
            "forgetting_rate": self.forgetting_rate,
            "difficulty_factor": self.difficulty_factor,
            "review_gain": self.review_gain,
            "review_count": self.review_count,
            "lapse_count": self.lapse_count,
            "last_reviewed_at": (
                None if self.last_reviewed_at is None else self.last_reviewed_at.isoformat()
            ),
            "last_activity_at": self.last_activity_at.isoformat(),
            "next_review_at": self.next_review_at.isoformat(),
            "risk_level": self.risk_level.value,
            "model_parameters": self.model_parameters,
            "computed_at": self.computed_at.isoformat(),
        }
        if canonical_sha256(document) != self.content_sha256:
            raise ValueError("content_sha256 does not match memory state")
        return self


class Topic2PathScoreComponentsV1(BaseModel):
    """Auditable weighted components used for one path-node decision."""

    model_config = FROZEN_MODEL_CONFIG

    mastery_deficit: float = Field(ge=0, le=1)
    memory_risk: float = Field(ge=0, le=1)
    misconception_severity: float = Field(ge=0, le=1)
    goal_alignment: float = Field(ge=0, le=1)
    topology_weight: float = Field(ge=0, le=1)
    difficulty_pace_fit: float = Field(ge=0, le=1)
    prerequisite_readiness: float = Field(ge=0, le=1)
    total: float = Field(ge=0, le=1)


class Topic2PathNodeV1(BaseModel):
    """One stable ordered learning node with explanation and tier assignment."""

    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic2.path-node.v1"] = "topic2.path-node.v1"
    order: int = Field(ge=0)
    kp_id: str = Field(min_length=6, max_length=120)
    title: str = Field(min_length=1, max_length=255)
    tier: Topic2LearningTier
    priority_score: float = Field(ge=0, le=1)
    score_components: Topic2PathScoreComponentsV1
    prerequisite_kp_ids: list[str] = Field(default_factory=list, max_length=500)
    estimated_minutes: int = Field(ge=1, le=2400)
    rationale_codes: list[str] = Field(min_length=1, max_length=32)


class Topic2GraphRepairV1(BaseModel):
    """Deterministic graph or manual-order repair applied before path release."""

    model_config = FROZEN_MODEL_CONFIG

    code: str = Field(min_length=1, max_length=64)
    edge_id: str | None = Field(default=None, max_length=128)
    detail: str = Field(min_length=1, max_length=2000)


class Topic2LearningPathSnapshotV1(BaseModel):
    """Immutable path snapshot bound to exact Topic 1 graph and profile versions."""

    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic2.learning-path-snapshot.v1"] = "topic2.learning-path-snapshot.v1"
    path_snapshot_id: UUID
    learner_ref: str = Field(min_length=3, max_length=256)
    course_id: str = Field(min_length=3, max_length=64)
    path_version: int = Field(ge=1)
    parent_path_snapshot_id: UUID | None = None
    topic1_graph_snapshot_id: UUID
    topic1_graph_version: int = Field(ge=1)
    profile_id: UUID
    plan_type: Topic2PathPlanType
    trigger_reason: str = Field(min_length=1, max_length=128)
    target_goal: str = Field(min_length=1, max_length=512)
    policy_version: VersionString
    path_document: dict[str, Any]
    decision_document: dict[str, Any]
    node_count: int = Field(ge=0, le=500)
    estimated_minutes: int = Field(ge=0, le=1_200_000)
    manual_override: bool
    content_sha256: Sha256Hex
    frozen_at: AwareDatetime

    @model_validator(mode="after")
    def validate_path(self) -> Topic2LearningPathSnapshotV1:
        nodes = self.path_document.get("nodes")
        if not isinstance(nodes, list) or len(nodes) != self.node_count:
            raise ValueError("path_document nodes do not match node_count")
        document = {
            "schema_version": self.schema_version,
            "path_snapshot_id": str(self.path_snapshot_id),
            "learner_ref": self.learner_ref,
            "course_id": self.course_id,
            "path_version": self.path_version,
            "parent_path_snapshot_id": (
                None if self.parent_path_snapshot_id is None else str(self.parent_path_snapshot_id)
            ),
            "topic1_graph_snapshot_id": str(self.topic1_graph_snapshot_id),
            "topic1_graph_version": self.topic1_graph_version,
            "profile_id": str(self.profile_id),
            "plan_type": self.plan_type.value,
            "trigger_reason": self.trigger_reason,
            "target_goal": self.target_goal,
            "policy_version": self.policy_version,
            "path_document": self.path_document,
            "decision_document": self.decision_document,
            "node_count": self.node_count,
            "estimated_minutes": self.estimated_minutes,
            "manual_override": self.manual_override,
            "frozen_at": self.frozen_at.isoformat(),
        }
        if canonical_sha256(document) != self.content_sha256:
            raise ValueError("content_sha256 does not match learning path snapshot")
        return self


class Topic2PathChangeV1(BaseModel):
    """Immutable delta explaining why a new learning path version was created."""

    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic2.path-change.v1"] = "topic2.path-change.v1"
    change_id: UUID
    learner_ref: str = Field(min_length=3, max_length=256)
    course_id: str = Field(min_length=3, max_length=64)
    from_path_snapshot_id: UUID | None = None
    to_path_snapshot_id: UUID
    change_type: Topic2PathChangeType
    reason: str = Field(min_length=1, max_length=2000)
    policy_version: VersionString
    change_document: dict[str, Any]
    occurred_at: AwareDatetime

    @model_validator(mode="after")
    def validate_endpoints(self) -> Topic2PathChangeV1:
        if self.from_path_snapshot_id == self.to_path_snapshot_id:
            raise ValueError("path change endpoints must differ")
        return self


class Topic2LearningPathRecordV1(BaseModel):
    """Persisted path snapshot, its change explanation, and audit provenance."""

    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic2.learning-path-record.v1"] = "topic2.learning-path-record.v1"
    snapshot: Topic2LearningPathSnapshotV1
    change: Topic2PathChangeV1
    audit_event_id: UUID
    created_by_subject: str = Field(min_length=1, max_length=256)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_binding(self) -> Topic2LearningPathRecordV1:
        if self.snapshot.path_snapshot_id != self.change.to_path_snapshot_id:
            raise ValueError("path record change target does not match snapshot")
        if self.snapshot.parent_path_snapshot_id != self.change.from_path_snapshot_id:
            raise ValueError("path record change source does not match parent")
        return self


class Topic2PathGenerateCommandV1(Topic2OperationCommandV1):
    """Replay-stable initial or replanned learning-path command."""

    schema_version: Literal["topic2.path-generate-command.v1"] = "topic2.path-generate-command.v1"
    target_goal: str = Field(min_length=1, max_length=512)
    target_kp_ids: list[str] | None = Field(default=None, max_length=500)
    manual_order: list[str] | None = Field(default=None, max_length=500)
    change_type: Topic2PathChangeType = Topic2PathChangeType.INITIALIZED
    trigger_reason: str = Field(default="PROFILE_OR_MEMORY_UPDATED", min_length=1, max_length=128)


class Topic2AgentContextV1(BaseModel):
    """Single personalization input consumed by Lecturer and Tester agents."""

    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic2.agent-context.v1"] = "topic2.agent-context.v1"
    learner_ref: str = Field(min_length=3, max_length=256)
    course_id: str = Field(min_length=3, max_length=64)
    profile: Topic2StudentProfileV1
    memory_states: list[Topic2MemoryStateV1] = Field(max_length=500)
    learning_path: Topic2LearningPathRecordV1
    personalization_policy_digest: Sha256Hex

    @model_validator(mode="after")
    def validate_context(self) -> Topic2AgentContextV1:
        if (
            self.profile.learner_ref != self.learner_ref
            or self.profile.course_id != self.course_id
            or self.learning_path.snapshot.learner_ref != self.learner_ref
            or self.learning_path.snapshot.course_id != self.course_id
            or any(
                item.learner_ref != self.learner_ref or item.course_id != self.course_id
                for item in self.memory_states
            )
        ):
            raise ValueError("agent context contains mixed learner or course identities")
        digest_document = {
            "profile_id": str(self.profile.profile_id),
            "profile_version": self.profile.profile_version,
            "memory_states": [
                {
                    "kp_id": item.kp_id,
                    "memory_state_id": str(item.memory_state_id),
                    "state_version": item.state_version,
                }
                for item in sorted(self.memory_states, key=lambda value: value.kp_id)
            ],
            "path_snapshot_id": str(self.learning_path.snapshot.path_snapshot_id),
            "path_version": self.learning_path.snapshot.path_version,
        }
        if canonical_sha256(digest_document) != self.personalization_policy_digest:
            raise ValueError("personalization_policy_digest does not match context bindings")
        return self
