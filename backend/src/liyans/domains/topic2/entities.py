from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

MAX_BEHAVIOR_PAYLOAD_BYTES = 64 * 1024


class ProfileDimension(StrEnum):
    KNOWLEDGE_MASTERY = "KNOWLEDGE_MASTERY"
    PROBLEM_SOLVING_PROFICIENCY = "PROBLEM_SOLVING_PROFICIENCY"
    MISCONCEPTION_PREFERENCE = "MISCONCEPTION_PREFERENCE"
    LEARNING_PACE = "LEARNING_PACE"
    FORGETTING_RATE = "FORGETTING_RATE"
    LEARNING_GOAL_TENDENCY = "LEARNING_GOAL_TENDENCY"


class BehaviorEventType(StrEnum):
    ANSWER_SUBMITTED = "ANSWER_SUBMITTED"
    RESOURCE_VIEWED = "RESOURCE_VIEWED"
    SIMULATION_RUN = "SIMULATION_RUN"
    REVIEW_COMPLETED = "REVIEW_COMPLETED"
    CODE_EXECUTED = "CODE_EXECUTED"
    SESSION_FOCUSED = "SESSION_FOCUSED"
    GOAL_SELECTED = "GOAL_SELECTED"


class BehaviorSourceType(StrEnum):
    LEARNER_UI = "LEARNER_UI"
    LECTURER = "LECTURER"
    MINDMAP = "MINDMAP"
    TESTER = "TESTER"
    CODE_SANDBOX = "CODE_SANDBOX"
    EXTENSION = "EXTENSION"
    SYSTEM = "SYSTEM"


class MemoryRiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PathPlanType(StrEnum):
    INITIAL = "INITIAL"
    REPLANNED = "REPLANNED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    RESTORED = "RESTORED"


class PathChangeType(StrEnum):
    INITIALIZED = "INITIALIZED"
    MEMORY_RISK = "MEMORY_RISK"
    MASTERY_DEFICIT = "MASTERY_DEFICIT"
    MISCONCEPTION = "MISCONCEPTION"
    GOAL_CHANGED = "GOAL_CHANGED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    TOPOLOGY_REPAIRED = "TOPOLOGY_REPAIRED"
    RESTORED = "RESTORED"


def _score(name: str, value: float) -> None:
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between zero and one")


def _aware(name: str, value: datetime | None) -> None:
    if value is not None and value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


def _sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class ProfileFeatureDraft:
    feature_id: UUID
    dimension: ProfileDimension
    feature_key: str
    value_document: dict[str, Any]
    normalized_score: float
    confidence: float
    evidence_count: int
    source_event_ids: tuple[str, ...]
    computed_at: datetime

    def __post_init__(self) -> None:
        _score("normalized_score", self.normalized_score)
        _score("confidence", self.confidence)
        _aware("computed_at", self.computed_at)
        if not self.feature_key or len(self.feature_key) > 160:
            raise ValueError("feature_key must contain between one and 160 characters")
        if self.evidence_count < 0:
            raise ValueError("evidence_count cannot be negative")


@dataclass(frozen=True, slots=True)
class StudentProfileDraft:
    profile_id: UUID
    learner_ref: str
    course_id: str
    profile_version: int
    parent_profile_id: UUID | None
    policy_version: str
    knowledge_mastery: float
    problem_solving_proficiency: float
    misconception_preference: float
    learning_pace: float
    forgetting_rate: float
    learning_goal_tendency: float
    confidence_score: float
    activity_count: int
    last_event_at: datetime | None
    source_window_start: datetime | None
    source_window_end: datetime | None
    profile_document: dict[str, Any]
    content_sha256: str
    frozen_at: datetime
    features: tuple[ProfileFeatureDraft, ...]

    def __post_init__(self) -> None:
        if self.profile_version < 1:
            raise ValueError("profile_version must be positive")
        if self.activity_count < 0:
            raise ValueError("activity_count cannot be negative")
        for name in (
            "knowledge_mastery",
            "problem_solving_proficiency",
            "misconception_preference",
            "learning_pace",
            "forgetting_rate",
            "learning_goal_tendency",
            "confidence_score",
        ):
            _score(name, float(getattr(self, name)))
        for name in (
            "last_event_at",
            "source_window_start",
            "source_window_end",
            "frozen_at",
        ):
            _aware(name, getattr(self, name))
        if (
            self.source_window_start is not None
            and self.source_window_end is not None
            and self.source_window_end < self.source_window_start
        ):
            raise ValueError("profile source window is reversed")
        if {feature.dimension for feature in self.features} != set(ProfileDimension):
            raise ValueError("a profile snapshot must contain all six dimensions")
        _sha256("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class StudentProfileRecord:
    draft: StudentProfileDraft
    audit_event_id: UUID
    created_by_subject: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LearningBehaviorEventDraft:
    event_id: UUID
    source_event_id: str
    event_version: int
    learner_ref: str
    course_id: str
    kp_id: str | None
    session_id: UUID | None
    event_type: BehaviorEventType
    source_type: BehaviorSourceType
    duration_seconds: float | None
    response_latency_ms: int | None
    correctness: float | None
    score: float | None
    attempt_count: int
    interaction_count: int
    attention_ratio: float | None
    misconception_ids: tuple[str, ...]
    goal_tags: tuple[str, ...]
    payload: dict[str, Any]
    payload_sha256: str
    occurred_at: datetime
    received_at: datetime

    def __post_init__(self) -> None:
        if self.event_version < 1:
            raise ValueError("event_version must be positive")
        if not self.source_event_id or len(self.source_event_id) > 160:
            raise ValueError("source_event_id must contain between one and 160 characters")
        if self.duration_seconds is not None and not 0 <= self.duration_seconds <= 86400:
            raise ValueError("duration_seconds is outside the accepted range")
        if self.response_latency_ms is not None and not 0 <= self.response_latency_ms <= 86400000:
            raise ValueError("response_latency_ms is outside the accepted range")
        for name in ("correctness", "score", "attention_ratio"):
            value = getattr(self, name)
            if value is not None:
                _score(name, value)
        if self.attempt_count < 0 or self.interaction_count < 0:
            raise ValueError("behavior counters cannot be negative")
        payload_bytes = json.dumps(
            self.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(payload_bytes) > MAX_BEHAVIOR_PAYLOAD_BYTES:
            raise ValueError(f"behavior payload cannot exceed {MAX_BEHAVIOR_PAYLOAD_BYTES} bytes")
        if len(self.misconception_ids) > 64 or len(self.goal_tags) > 32:
            raise ValueError("behavior tag collections exceed the accepted limit")
        _aware("occurred_at", self.occurred_at)
        _aware("received_at", self.received_at)
        _sha256("payload_sha256", self.payload_sha256)


@dataclass(frozen=True, slots=True)
class LearningBehaviorEventRecord:
    draft: LearningBehaviorEventDraft
    audit_event_id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryStateDraft:
    memory_state_id: UUID
    learner_ref: str
    course_id: str
    kp_id: str
    state_version: int
    parent_memory_state_id: UUID | None
    model_version: str
    stability_days: float
    effective_stability_days: float
    elapsed_days: float
    retrievability: float
    forgetting_rate: float
    difficulty_factor: float
    review_gain: float
    review_count: int
    lapse_count: int
    last_reviewed_at: datetime | None
    last_activity_at: datetime
    next_review_at: datetime
    risk_level: MemoryRiskLevel
    model_parameters: dict[str, Any]
    content_sha256: str
    computed_at: datetime

    def __post_init__(self) -> None:
        if self.state_version < 1:
            raise ValueError("state_version must be positive")
        if not 0 < self.stability_days <= 36500:
            raise ValueError("stability_days is outside the accepted range")
        if not 0 < self.effective_stability_days <= 36500:
            raise ValueError("effective_stability_days is outside the accepted range")
        if self.elapsed_days < 0:
            raise ValueError("elapsed_days cannot be negative")
        _score("retrievability", self.retrievability)
        _score("forgetting_rate", self.forgetting_rate)
        if not 0.25 <= self.difficulty_factor <= 4:
            raise ValueError("difficulty_factor is outside the accepted range")
        if not 0 <= self.review_gain <= 16:
            raise ValueError("review_gain is outside the accepted range")
        if self.review_count < 0 or not 0 <= self.lapse_count <= self.review_count:
            raise ValueError("memory review counters are inconsistent")
        for name in (
            "last_reviewed_at",
            "last_activity_at",
            "next_review_at",
            "computed_at",
        ):
            _aware(name, getattr(self, name))
        _sha256("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class MemoryStateRecord:
    draft: MemoryStateDraft
    audit_event_id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LearningPathSnapshotDraft:
    path_snapshot_id: UUID
    learner_ref: str
    course_id: str
    path_version: int
    parent_path_snapshot_id: UUID | None
    topic1_graph_snapshot_id: UUID
    topic1_graph_version: int
    profile_id: UUID
    plan_type: PathPlanType
    trigger_reason: str
    target_goal: str
    policy_version: str
    path_document: dict[str, Any]
    decision_document: dict[str, Any]
    node_count: int
    estimated_minutes: int
    manual_override: bool
    content_sha256: str
    frozen_at: datetime

    def __post_init__(self) -> None:
        if self.path_version < 1 or self.topic1_graph_version < 1:
            raise ValueError("path and Topic 1 graph versions must be positive")
        if self.node_count < 0 or self.estimated_minutes < 0:
            raise ValueError("path counts cannot be negative")
        if not self.trigger_reason or len(self.trigger_reason) > 128:
            raise ValueError("trigger_reason must contain between one and 128 characters")
        if not self.target_goal or len(self.target_goal) > 512:
            raise ValueError("target_goal must contain between one and 512 characters")
        _aware("frozen_at", self.frozen_at)
        _sha256("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class PathChangeDraft:
    change_id: UUID
    learner_ref: str
    course_id: str
    from_path_snapshot_id: UUID | None
    to_path_snapshot_id: UUID
    change_type: PathChangeType
    reason: str
    policy_version: str
    change_document: dict[str, Any]
    occurred_at: datetime

    def __post_init__(self) -> None:
        if self.from_path_snapshot_id == self.to_path_snapshot_id:
            raise ValueError("path change endpoints must differ")
        if not self.reason or len(self.reason) > 2000:
            raise ValueError("path change reason must contain between one and 2000 characters")
        _aware("occurred_at", self.occurred_at)


@dataclass(frozen=True, slots=True)
class LearningPathRecord:
    draft: LearningPathSnapshotDraft
    change: PathChangeDraft
    audit_event_id: UUID
    created_by_subject: str
    created_at: datetime
