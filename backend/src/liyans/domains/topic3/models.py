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

TOPIC3_TENANT_TABLES = (
    "topic3_generation_sessions",
    "topic3_execution_blueprints",
    "topic3_agent_tasks",
    "topic3_generated_candidates",
    "topic3_model_invocations",
    "topic3_stream_chunks",
)


class Topic3GenerationSessionModel(Base):
    """Immutable generation-session state snapshot."""

    __tablename__ = "topic3_generation_sessions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "session_snapshot_id"),
        UniqueConstraint("tenant_id", "generation_session_id", "session_version"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_session_snapshot_id"],
            [
                "topic3_generation_sessions.tenant_id",
                "topic3_generation_sessions.session_snapshot_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "topic1_graph_snapshot_id"],
            ["topic1_graph_snapshots.tenant_id", "topic1_graph_snapshots.snapshot_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "topic2_profile_id"],
            ["topic2_student_profiles.tenant_id", "topic2_student_profiles.profile_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "topic2_path_snapshot_id"],
            [
                "topic2_learning_path_snapshots.tenant_id",
                "topic2_learning_path_snapshots.path_snapshot_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("session_version >= 1", name="positive_session_version"),
        CheckConstraint(
            "state IN ('PLANNED', 'RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED', 'CANCELLED')",
            name="state",
        ),
        CheckConstraint("topic1_graph_version >= 1", name="positive_graph_version"),
        CheckConstraint("topic2_profile_version >= 1", name="positive_profile_version"),
        CheckConstraint("topic2_path_version >= 1", name="positive_path_version"),
        CheckConstraint(
            "personalization_policy_digest ~ '^[0-9a-f]{64}$'",
            name="personalization_digest_format",
        ),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        CheckConstraint("jsonb_typeof(request_document) = 'object'", name="request_object"),
        CheckConstraint("jsonb_typeof(result_document) = 'object'", name="result_object"),
        CheckConstraint("jsonb_typeof(requested_resources) = 'array'", name="resources_array"),
        Index(
            "ix_topic3_sessions_learner_created",
            "tenant_id",
            "learner_ref",
            "course_id",
            "created_at",
        ),
        Index(
            "ix_topic3_sessions_logical_version",
            "tenant_id",
            "generation_session_id",
            "session_version",
        ),
    )

    session_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False
    )
    generation_session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    session_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_session_snapshot_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    learner_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    course_id: Mapped[str] = mapped_column(String(64), nullable=False)
    topic1_graph_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    topic1_graph_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    topic2_profile_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    topic2_profile_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    topic2_path_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    topic2_path_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    personalization_policy_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_resources: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    request_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_document: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
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
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Topic3ExecutionBlueprintModel(Base):
    """Immutable execution plan binding Topic 1 and Topic 2 snapshots."""

    __tablename__ = "topic3_execution_blueprints"
    __table_args__ = (
        UniqueConstraint("tenant_id", "blueprint_snapshot_id"),
        UniqueConstraint("tenant_id", "blueprint_id", "blueprint_version"),
        ForeignKeyConstraint(
            ["tenant_id", "generation_session_id", "generation_session_version"],
            [
                "topic3_generation_sessions.tenant_id",
                "topic3_generation_sessions.generation_session_id",
                "topic3_generation_sessions.session_version",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("generation_session_version >= 1", name="positive_session_version"),
        CheckConstraint("max_parallelism BETWEEN 1 AND 5", name="parallelism_range"),
        CheckConstraint("step_count BETWEEN 1 AND 5", name="step_count_range"),
        CheckConstraint("blueprint_sha256 ~ '^[0-9a-f]{64}$'", name="blueprint_sha256_format"),
        CheckConstraint(
            "personalization_policy_digest ~ '^[0-9a-f]{64}$'",
            name="personalization_digest_format",
        ),
        CheckConstraint("jsonb_typeof(blueprint_document) = 'object'", name="blueprint_object"),
        CheckConstraint("jsonb_typeof(steps_document) = 'array'", name="steps_array"),
        CheckConstraint("jsonb_typeof(activation_document) = 'object'", name="activation_object"),
        Index(
            "ix_topic3_blueprints_session_version",
            "tenant_id",
            "generation_session_id",
            "generation_session_version",
        ),
    )

    blueprint_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False
    )
    blueprint_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    blueprint_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generation_session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    generation_session_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    personalization_policy_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    max_parallelism: Mapped[int] = mapped_column(Integer, nullable=False)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False)
    activation_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    steps_document: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    blueprint_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    blueprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_by_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Topic3AgentTaskModel(Base):
    """Append-only task state and result record for one blueprint step."""

    __tablename__ = "topic3_agent_tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "task_record_id"),
        UniqueConstraint("tenant_id", "task_id", "task_version"),
        ForeignKeyConstraint(
            ["tenant_id", "blueprint_id", "blueprint_version"],
            [
                "topic3_execution_blueprints.tenant_id",
                "topic3_execution_blueprints.blueprint_id",
                "topic3_execution_blueprints.blueprint_version",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("task_version >= 1", name="positive_task_version"),
        CheckConstraint(
            "agent IN ('Lecturer', 'MindMap', 'Tester', 'CodeSandbox', 'Extension')",
            name="agent",
        ),
        CheckConstraint(
            "resource_type IN ('Lecturer_Doc', 'MindMap', 'Gradient_Quiz', "
            "'Simulation_Code', 'Extension_Material')",
            name="resource_type",
        ),
        CheckConstraint(
            "state IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'SKIPPED', 'CANCELLED')",
            name="state",
        ),
        CheckConstraint("attempt BETWEEN 0 AND max_attempts", name="attempt_budget"),
        CheckConstraint("max_attempts BETWEEN 1 AND 8", name="max_attempts"),
        CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'", name="request_sha256_format"),
        CheckConstraint(
            "result_sha256 IS NULL OR result_sha256 ~ '^[0-9a-f]{64}$'",
            name="result_sha256_format",
        ),
        CheckConstraint("jsonb_typeof(dependency_task_ids) = 'array'", name="dependencies_array"),
        CheckConstraint("jsonb_typeof(request_document) = 'object'", name="request_object"),
        CheckConstraint("jsonb_typeof(result_document) = 'object'", name="result_object"),
        CheckConstraint("jsonb_typeof(error_document) = 'object'", name="error_object"),
        Index(
            "ix_topic3_tasks_blueprint_state",
            "tenant_id",
            "blueprint_id",
            "blueprint_version",
            "state",
        ),
        Index("ix_topic3_tasks_logical_version", "tenant_id", "task_id", "task_version"),
    )

    task_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    task_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    blueprint_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    blueprint_version: Mapped[str] = mapped_column(String(64), nullable=False)
    agent: Mapped[str] = mapped_column(String(24), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    dependency_task_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    request_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_document: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    error_document: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audit_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Topic3GeneratedCandidateModel(Base):
    """Immutable canonical CandidateV1 persistence record."""

    __tablename__ = "topic3_generated_candidates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "candidate_record_id"),
        UniqueConstraint("tenant_id", "candidate_id", "candidate_version"),
        ForeignKeyConstraint(
            ["tenant_id", "blueprint_id", "blueprint_version"],
            [
                "topic3_execution_blueprints.tenant_id",
                "topic3_execution_blueprints.blueprint_id",
                "topic3_execution_blueprints.blueprint_version",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("candidate_version >= 1", name="positive_candidate_version"),
        CheckConstraint(
            "agent IN ('Lecturer', 'MindMap', 'Tester', 'CodeSandbox', 'Extension')",
            name="agent",
        ),
        CheckConstraint(
            "resource_type IN ('Lecturer_Doc', 'MindMap', 'Gradient_Quiz', "
            "'Simulation_Code', 'Extension_Material')",
            name="resource_type",
        ),
        CheckConstraint(
            "state IN ('GENERATING', 'COMPLETE', 'FAILED', 'SUPERSEDED')",
            name="state",
        ),
        CheckConstraint("candidate_sha256 ~ '^[0-9a-f]{64}$'", name="candidate_sha256_format"),
        CheckConstraint(
            "personalization_policy_digest ~ '^[0-9a-f]{64}$'",
            name="personalization_digest_format",
        ),
        CheckConstraint("jsonb_typeof(candidate_document) = 'object'", name="candidate_object"),
        Index(
            "ix_topic3_candidates_blueprint_created",
            "tenant_id",
            "blueprint_id",
            "blueprint_version",
            "created_at",
        ),
        Index(
            "ix_topic3_candidates_resource_created",
            "tenant_id",
            "resource_type",
            "created_at",
        ),
    )

    candidate_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False
    )
    candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    blueprint_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    blueprint_version: Mapped[str] = mapped_column(String(64), nullable=False)
    agent: Mapped[str] = mapped_column(String(24), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    candidate_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    candidate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    personalization_policy_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Topic3ModelInvocationModel(Base):
    """Redacted provider invocation evidence without credentials or raw secrets."""

    __tablename__ = "topic3_model_invocations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "invocation_id"),
        UniqueConstraint("tenant_id", "provider_alias", "provider_request_id"),
        ForeignKeyConstraint(
            ["tenant_id", "task_id", "task_version"],
            [
                "topic3_agent_tasks.tenant_id",
                "topic3_agent_tasks.task_id",
                "topic3_agent_tasks.task_version",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "provider_alias IN ('spark_text', 'xfyun_code', 'seedance', 'local')",
            name="provider_alias",
        ),
        CheckConstraint("state IN ('SUCCEEDED', 'FAILED', 'TIMEOUT')", name="state"),
        CheckConstraint("latency_ms >= 0", name="nonnegative_latency"),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="input_tokens"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="output_tokens"),
        CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'", name="request_sha256_format"),
        CheckConstraint(
            "response_sha256 IS NULL OR response_sha256 ~ '^[0-9a-f]{64}$'",
            name="response_sha256_format",
        ),
        CheckConstraint("jsonb_typeof(error_document) = 'object'", name="error_object"),
        Index(
            "ix_topic3_invocations_task_started",
            "tenant_id",
            "task_id",
            "task_version",
            "started_at",
        ),
    )

    invocation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    task_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider_alias: Mapped[str] = mapped_column(String(32), nullable=False)
    model_alias: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_request_id: Mapped[str] = mapped_column(String(256), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response_sha256: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_document: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Topic3StreamChunkModel(Base):
    """Immutable staged SSE fragment used before Topic 4 release authorization."""

    __tablename__ = "topic3_stream_chunks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "stream_chunk_record_id"),
        UniqueConstraint("tenant_id", "fragment_id"),
        UniqueConstraint(
            "tenant_id",
            "stream_id",
            "candidate_id",
            "candidate_version",
            "block_partition",
            "chunk_index",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "candidate_id", "candidate_version"],
            [
                "topic3_generated_candidates.tenant_id",
                "topic3_generated_candidates.candidate_id",
                "topic3_generated_candidates.candidate_version",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("candidate_version >= 1", name="positive_candidate_version"),
        CheckConstraint(
            "fragment_type IN ('START', 'DELTA', 'END', 'SNAPSHOT')", name="fragment_type"
        ),
        CheckConstraint("chunk_index >= 0", name="nonnegative_chunk_index"),
        CheckConstraint("data_encoding IN ('utf-8-json', 'utf-8-text')", name="data_encoding"),
        CheckConstraint("octet_length(data) <= 65536", name="data_size"),
        CheckConstraint("data_sha256 ~ '^[0-9a-f]{64}$'", name="data_sha256_format"),
        CheckConstraint(
            "(fragment_type = 'END' AND is_final) OR fragment_type <> 'END'",
            name="end_is_final",
        ),
        Index(
            "ix_topic3_stream_chunks_stream_order",
            "tenant_id",
            "stream_id",
            "candidate_id",
            "candidate_version",
            "block_partition",
            "chunk_index",
        ),
        Index("ix_topic3_stream_chunks_emitted", "tenant_id", "emitted_at"),
    )

    stream_chunk_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False
    )
    stream_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    fragment_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    block_id: Mapped[str | None] = mapped_column(String(128))
    block_partition: Mapped[str] = mapped_column(String(128), nullable=False)
    fragment_type: Mapped[str] = mapped_column(String(16), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False)
    data_encoding: Mapped[str] = mapped_column(String(16), nullable=False)
    data: Mapped[str] = mapped_column(String(65536), nullable=False)
    data_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    emitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
