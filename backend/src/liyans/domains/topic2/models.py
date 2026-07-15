from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from liyans.infrastructure.database.models import Base

TOPIC2_TENANT_TABLES = (
    "topic2_student_profiles",
    "topic2_profile_features",
    "topic2_learning_behavior_events",
    "topic2_memory_states",
    "topic2_learning_path_snapshots",
    "topic2_path_change_logs",
)

PROFILE_DIMENSIONS = (
    "KNOWLEDGE_MASTERY",
    "PROBLEM_SOLVING_PROFICIENCY",
    "MISCONCEPTION_PREFERENCE",
    "LEARNING_PACE",
    "FORGETTING_RATE",
    "LEARNING_GOAL_TENDENCY",
)


class Topic2StudentProfileModel(Base):
    """Immutable aggregate snapshot for one learner and Topic 1 course."""

    __tablename__ = "topic2_student_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "profile_id"),
        UniqueConstraint("tenant_id", "profile_id", "learner_ref", "course_id"),
        UniqueConstraint("tenant_id", "learner_ref", "course_id", "profile_version"),
        ForeignKeyConstraint(
            ["tenant_id", "course_id"],
            ["topic1_courses.tenant_id", "topic1_courses.course_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_profile_id", "learner_ref", "course_id"],
            [
                "topic2_student_profiles.tenant_id",
                "topic2_student_profiles.profile_id",
                "topic2_student_profiles.learner_ref",
                "topic2_student_profiles.course_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("profile_version >= 1", name="positive_profile_version"),
        CheckConstraint("knowledge_mastery BETWEEN 0 AND 1", name="knowledge_mastery"),
        CheckConstraint(
            "problem_solving_proficiency BETWEEN 0 AND 1",
            name="problem_solving_proficiency",
        ),
        CheckConstraint(
            "misconception_preference BETWEEN 0 AND 1",
            name="misconception_preference",
        ),
        CheckConstraint("learning_pace BETWEEN 0 AND 1", name="learning_pace"),
        CheckConstraint("forgetting_rate BETWEEN 0 AND 1", name="forgetting_rate"),
        CheckConstraint(
            "learning_goal_tendency BETWEEN 0 AND 1",
            name="learning_goal_tendency",
        ),
        CheckConstraint("confidence_score BETWEEN 0 AND 1", name="confidence_score"),
        CheckConstraint("activity_count >= 0", name="nonnegative_activity_count"),
        CheckConstraint(
            "source_window_start IS NULL OR source_window_end IS NULL "
            "OR source_window_end >= source_window_start",
            name="source_window_order",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="content_sha256_format",
        ),
        CheckConstraint(
            "jsonb_typeof(profile_document) = 'object'",
            name="profile_document_object",
        ),
        Index(
            "ix_topic2_student_profiles_learner_version",
            "tenant_id",
            "learner_ref",
            "course_id",
            "profile_version",
        ),
        Index(
            "ix_topic2_student_profiles_course_frozen",
            "tenant_id",
            "course_id",
            "frozen_at",
        ),
    )

    profile_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    learner_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    course_id: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_profile_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    knowledge_mastery: Mapped[float] = mapped_column(Float, nullable=False)
    problem_solving_proficiency: Mapped[float] = mapped_column(Float, nullable=False)
    misconception_preference: Mapped[float] = mapped_column(Float, nullable=False)
    learning_pace: Mapped[float] = mapped_column(Float, nullable=False)
    forgetting_rate: Mapped[float] = mapped_column(Float, nullable=False)
    learning_goal_tendency: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    activity_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    profile_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_by_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Topic2ProfileFeatureModel(Base):
    """Immutable evidence-backed feature belonging to a profile snapshot."""

    __tablename__ = "topic2_profile_features"
    __table_args__ = (
        UniqueConstraint("tenant_id", "feature_id"),
        UniqueConstraint("tenant_id", "profile_id", "dimension", "feature_key"),
        ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["topic2_student_profiles.tenant_id", "topic2_student_profiles.profile_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "dimension IN ("
            "'KNOWLEDGE_MASTERY', 'PROBLEM_SOLVING_PROFICIENCY', "
            "'MISCONCEPTION_PREFERENCE', 'LEARNING_PACE', "
            "'FORGETTING_RATE', 'LEARNING_GOAL_TENDENCY')",
            name="dimension",
        ),
        CheckConstraint("normalized_score BETWEEN 0 AND 1", name="normalized_score"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence"),
        CheckConstraint("evidence_count >= 0", name="nonnegative_evidence_count"),
        CheckConstraint(
            "jsonb_typeof(value_document) = 'object'",
            name="value_document_object",
        ),
        CheckConstraint(
            "jsonb_typeof(source_event_ids) = 'array'",
            name="source_event_ids_array",
        ),
        Index(
            "ix_topic2_profile_features_profile_dimension",
            "tenant_id",
            "profile_id",
            "dimension",
        ),
    )

    feature_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    profile_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    dimension: Mapped[str] = mapped_column(String(48), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(160), nullable=False)
    value_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    normalized_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_event_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Topic2LearningBehaviorEventModel(Base):
    """Append-only, tokenized learner interaction used for silent profiling."""

    __tablename__ = "topic2_learning_behavior_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id"),
        UniqueConstraint("tenant_id", "source_event_id"),
        ForeignKeyConstraint(
            ["tenant_id", "course_id"],
            ["topic1_courses.tenant_id", "topic1_courses.course_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "course_id", "kp_id"],
            [
                "topic1_knowledge_points.tenant_id",
                "topic1_knowledge_points.course_id",
                "topic1_knowledge_points.kp_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("event_version >= 1", name="positive_event_version"),
        CheckConstraint(
            "event_type IN ("
            "'ANSWER_SUBMITTED', 'RESOURCE_VIEWED', 'SIMULATION_RUN', "
            "'REVIEW_COMPLETED', 'CODE_EXECUTED', 'SESSION_FOCUSED', "
            "'GOAL_SELECTED')",
            name="event_type",
        ),
        CheckConstraint(
            "source_type IN ("
            "'LEARNER_UI', 'LECTURER', 'MINDMAP', 'TESTER', "
            "'CODE_SANDBOX', 'EXTENSION', 'SYSTEM')",
            name="source_type",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds BETWEEN 0 AND 86400",
            name="duration_seconds",
        ),
        CheckConstraint(
            "response_latency_ms IS NULL OR response_latency_ms BETWEEN 0 AND 86400000",
            name="response_latency_ms",
        ),
        CheckConstraint(
            "correctness IS NULL OR correctness BETWEEN 0 AND 1",
            name="correctness",
        ),
        CheckConstraint("score IS NULL OR score BETWEEN 0 AND 1", name="score"),
        CheckConstraint("attempt_count >= 0", name="nonnegative_attempt_count"),
        CheckConstraint("interaction_count >= 0", name="nonnegative_interaction_count"),
        CheckConstraint(
            "attention_ratio IS NULL OR attention_ratio BETWEEN 0 AND 1",
            name="attention_ratio",
        ),
        CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="payload_sha256_format",
        ),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        CheckConstraint(
            "jsonb_typeof(misconception_ids) = 'array'",
            name="misconception_ids_array",
        ),
        CheckConstraint("jsonb_typeof(goal_tags) = 'array'", name="goal_tags_array"),
        Index(
            "ix_topic2_behavior_learner_occurred",
            "tenant_id",
            "learner_ref",
            "course_id",
            "occurred_at",
        ),
        Index(
            "ix_topic2_behavior_learner_received",
            "tenant_id",
            "learner_ref",
            "course_id",
            "received_at",
            "event_id",
        ),
        Index(
            "ix_topic2_behavior_kp_occurred",
            "tenant_id",
            "course_id",
            "kp_id",
            "occurred_at",
        ),
    )

    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    learner_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    course_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kp_id: Mapped[str | None] = mapped_column(String(120))
    session_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    response_latency_ms: Mapped[int | None] = mapped_column(Integer)
    correctness: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float | None] = mapped_column(Float)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    interaction_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    attention_ratio: Mapped[float | None] = mapped_column(Float)
    misconception_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    goal_tags: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Topic2MemoryStateModel(Base):
    """Immutable Ebbinghaus-model state for one learner and knowledge point."""

    __tablename__ = "topic2_memory_states"
    __table_args__ = (
        UniqueConstraint("tenant_id", "memory_state_id"),
        UniqueConstraint(
            "tenant_id",
            "memory_state_id",
            "learner_ref",
            "course_id",
            "kp_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "learner_ref",
            "course_id",
            "kp_id",
            "state_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "course_id", "kp_id"],
            [
                "topic1_knowledge_points.tenant_id",
                "topic1_knowledge_points.course_id",
                "topic1_knowledge_points.kp_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "parent_memory_state_id",
                "learner_ref",
                "course_id",
                "kp_id",
            ],
            [
                "topic2_memory_states.tenant_id",
                "topic2_memory_states.memory_state_id",
                "topic2_memory_states.learner_ref",
                "topic2_memory_states.course_id",
                "topic2_memory_states.kp_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("state_version >= 1", name="positive_state_version"),
        CheckConstraint("stability_days > 0 AND stability_days <= 36500", name="stability_days"),
        CheckConstraint(
            "effective_stability_days > 0 AND effective_stability_days <= 36500",
            name="effective_stability_days",
        ),
        CheckConstraint("elapsed_days >= 0", name="nonnegative_elapsed_days"),
        CheckConstraint("retrievability BETWEEN 0 AND 1", name="retrievability"),
        CheckConstraint("forgetting_rate BETWEEN 0 AND 1", name="forgetting_rate"),
        CheckConstraint(
            "difficulty_factor BETWEEN 0.25 AND 4",
            name="difficulty_factor",
        ),
        CheckConstraint("review_gain >= 0 AND review_gain <= 16", name="review_gain"),
        CheckConstraint("review_count >= 0", name="nonnegative_review_count"),
        CheckConstraint("lapse_count >= 0", name="nonnegative_lapse_count"),
        CheckConstraint("lapse_count <= review_count", name="lapse_not_above_review"),
        CheckConstraint(
            "risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="risk_level",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="content_sha256_format",
        ),
        CheckConstraint(
            "jsonb_typeof(model_parameters) = 'object'",
            name="model_parameters_object",
        ),
        Index(
            "ix_topic2_memory_learner_kp_version",
            "tenant_id",
            "learner_ref",
            "course_id",
            "kp_id",
            "state_version",
        ),
        Index(
            "ix_topic2_memory_review_due",
            "tenant_id",
            "next_review_at",
            "risk_level",
        ),
    )

    memory_state_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    learner_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    course_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kp_id: Mapped[str] = mapped_column(String(120), nullable=False)
    state_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_memory_state_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    stability_days: Mapped[float] = mapped_column(Float, nullable=False)
    effective_stability_days: Mapped[float] = mapped_column(Float, nullable=False)
    elapsed_days: Mapped[float] = mapped_column(Float, nullable=False)
    retrievability: Mapped[float] = mapped_column(Float, nullable=False)
    forgetting_rate: Mapped[float] = mapped_column(Float, nullable=False)
    difficulty_factor: Mapped[float] = mapped_column(Float, nullable=False)
    review_gain: Mapped[float] = mapped_column(Float, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    lapse_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_review_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    model_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Topic2LearningPathSnapshotModel(Base):
    """Immutable, explainable learning-path decision snapshot."""

    __tablename__ = "topic2_learning_path_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "path_snapshot_id"),
        UniqueConstraint(
            "tenant_id",
            "path_snapshot_id",
            "learner_ref",
            "course_id",
        ),
        UniqueConstraint("tenant_id", "learner_ref", "course_id", "path_version"),
        ForeignKeyConstraint(
            ["tenant_id", "course_id"],
            ["topic1_courses.tenant_id", "topic1_courses.course_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "topic1_graph_snapshot_id"],
            ["topic1_graph_snapshots.tenant_id", "topic1_graph_snapshots.snapshot_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "profile_id", "learner_ref", "course_id"],
            [
                "topic2_student_profiles.tenant_id",
                "topic2_student_profiles.profile_id",
                "topic2_student_profiles.learner_ref",
                "topic2_student_profiles.course_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "parent_path_snapshot_id",
                "learner_ref",
                "course_id",
            ],
            [
                "topic2_learning_path_snapshots.tenant_id",
                "topic2_learning_path_snapshots.path_snapshot_id",
                "topic2_learning_path_snapshots.learner_ref",
                "topic2_learning_path_snapshots.course_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("path_version >= 1", name="positive_path_version"),
        CheckConstraint("topic1_graph_version >= 1", name="positive_graph_version"),
        CheckConstraint(
            "plan_type IN ('INITIAL', 'REPLANNED', 'MANUAL_OVERRIDE', 'RESTORED')",
            name="plan_type",
        ),
        CheckConstraint("node_count >= 0", name="nonnegative_node_count"),
        CheckConstraint("estimated_minutes >= 0", name="nonnegative_estimated_minutes"),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="content_sha256_format",
        ),
        CheckConstraint(
            "jsonb_typeof(path_document) = 'object'",
            name="path_document_object",
        ),
        CheckConstraint(
            "jsonb_typeof(decision_document) = 'object'",
            name="decision_document_object",
        ),
        Index(
            "ix_topic2_paths_learner_version",
            "tenant_id",
            "learner_ref",
            "course_id",
            "path_version",
        ),
        Index(
            "ix_topic2_paths_graph_snapshot",
            "tenant_id",
            "topic1_graph_snapshot_id",
        ),
    )

    path_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    learner_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    course_id: Mapped[str] = mapped_column(String(64), nullable=False)
    path_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_path_snapshot_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    topic1_graph_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    topic1_graph_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    profile_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    plan_type: Mapped[str] = mapped_column(String(24), nullable=False)
    trigger_reason: Mapped[str] = mapped_column(String(128), nullable=False)
    target_goal: Mapped[str] = mapped_column(String(512), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    path_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    decision_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    manual_override: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_by_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Topic2PathChangeLogModel(Base):
    """Immutable explanation of the delta between two path snapshots."""

    __tablename__ = "topic2_path_change_logs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "change_id"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "from_path_snapshot_id",
                "learner_ref",
                "course_id",
            ],
            [
                "topic2_learning_path_snapshots.tenant_id",
                "topic2_learning_path_snapshots.path_snapshot_id",
                "topic2_learning_path_snapshots.learner_ref",
                "topic2_learning_path_snapshots.course_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "to_path_snapshot_id",
                "learner_ref",
                "course_id",
            ],
            [
                "topic2_learning_path_snapshots.tenant_id",
                "topic2_learning_path_snapshots.path_snapshot_id",
                "topic2_learning_path_snapshots.learner_ref",
                "topic2_learning_path_snapshots.course_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "change_type IN ("
            "'INITIALIZED', 'MEMORY_RISK', 'MASTERY_DEFICIT', "
            "'MISCONCEPTION', 'GOAL_CHANGED', 'MANUAL_OVERRIDE', "
            "'TOPOLOGY_REPAIRED', 'RESTORED')",
            name="change_type",
        ),
        CheckConstraint(
            "from_path_snapshot_id IS NULL OR from_path_snapshot_id <> to_path_snapshot_id",
            name="distinct_path_snapshots",
        ),
        CheckConstraint(
            "jsonb_typeof(change_document) = 'object'",
            name="change_document_object",
        ),
        Index(
            "ix_topic2_path_changes_to_snapshot",
            "tenant_id",
            "to_path_snapshot_id",
        ),
        Index(
            "ix_topic2_path_changes_learner_occurred",
            "tenant_id",
            "learner_ref",
            "course_id",
            "occurred_at",
        ),
    )

    change_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    learner_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    course_id: Mapped[str] = mapped_column(String(64), nullable=False)
    from_path_snapshot_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    to_path_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    change_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    change_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    audit_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
