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
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from liyans.infrastructure.database.models import Base
from liyans.infrastructure.database.topic4 import (
    Topic4ImmutableRecordMixin,
    topic4_record_constraints,
)

TOPIC4_CONTROL_TABLES = (
    "topic4_verifications",
    "topic4_verification_states",
    "topic4_claims",
    "topic4_claim_risks",
    "topic4_dispatch_plans",
    "topic4_module_runs",
    "topic4_module_results",
    "topic4_claim_verdicts",
    "topic4_aggregation_results",
    "topic4_verification_reports",
    "topic4_human_review_tasks",
    "topic4_human_review_decisions",
)

VERIFICATION_STATES_SQL = (
    "'ACCEPTED', 'SNAPSHOT_VALIDATING', 'CLAIM_EXTRACTING', 'CLAIMS_READY', "
    "'MODULE_DISPATCHING', 'VERIFYING', 'AGGREGATING', 'REVISION_PLANNING', "
    "'REVISION_WAITING', 'REVERIFYING', 'RELEASE_PENDING', 'RELEASED', "
    "'BLOCKED', 'REVIEW_REQUIRED', 'FAILED', 'EXPIRED', 'CANCELLED'"
)


class Topic4VerificationModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_verifications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "verification_id"),
        UniqueConstraint("tenant_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_verification_id"],
            ["topic4_verifications.tenant_id", "topic4_verifications.verification_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_candidate_id", "source_candidate_version"],
            [
                "topic3_generated_candidates.tenant_id",
                "topic3_generated_candidates.candidate_id",
                "topic3_generated_candidates.candidate_version",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("source_candidate_version >= 1", name="positive_candidate_version"),
        CheckConstraint(
            "source_candidate_sha256 ~ '^[0-9a-f]{64}$'", name="candidate_sha256_format"
        ),
        CheckConstraint(
            "trigger IN ('INITIAL_GENERATION', 'REVISION_REVERIFY', 'MANUAL_REVERIFY', "
            "'KNOWLEDGE_BASE_REVALIDATION', 'POLICY_REVALIDATION')",
            name="trigger",
        ),
        CheckConstraint(
            "requested_profile IN ('STANDARD', 'STRICT', 'CODE_STRICT')",
            name="requested_profile",
        ),
        CheckConstraint("deadline_at > accepted_at", name="deadline_after_acceptance"),
        CheckConstraint("jsonb_typeof(binding_document) = 'object'", name="binding_object"),
        CheckConstraint("jsonb_typeof(accepted_document) = 'object'", name="accepted_object"),
        CheckConstraint("jsonb_typeof(request_document) = 'object'", name="request_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_verifications_candidate",
            "tenant_id",
            "source_candidate_id",
            "source_candidate_version",
        ),
        Index("ix_topic4_verifications_deadline", "tenant_id", "deadline_at"),
    )

    verification_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    trigger: Mapped[str] = mapped_column(String(40), nullable=False)
    parent_verification_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    source_candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_candidate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_profile: Mapped[str] = mapped_column(String(24), nullable=False)
    binding_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    accepted_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    request_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Topic4VerificationStateModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_verification_states"
    __table_args__ = (
        UniqueConstraint("tenant_id", "state_snapshot_id"),
        UniqueConstraint("tenant_id", "verification_id", "state_version"),
        ForeignKeyConstraint(
            ["tenant_id", "verification_id"],
            ["topic4_verifications.tenant_id", "topic4_verifications.verification_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("state_version >= 1", name="positive_state_version"),
        CheckConstraint("version_cas = state_version", name="cas_matches_state_version"),
        CheckConstraint(f"current_state IN ({VERIFICATION_STATES_SQL})", name="current_state"),
        CheckConstraint(
            f"previous_state IS NULL OR previous_state IN ({VERIFICATION_STATES_SQL})",
            name="previous_state",
        ),
        CheckConstraint("revision_round BETWEEN 0 AND 2", name="revision_round"),
        CheckConstraint("jsonb_typeof(state_document) = 'object'", name="state_object"),
        *topic4_record_constraints(),
        Index("ix_topic4_states_current", "tenant_id", "verification_id", "state_version"),
        Index("ix_topic4_states_state_changed", "tenant_id", "current_state", "changed_at"),
    )

    state_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    state_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(32))
    current_state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    revision_round: Mapped[int] = mapped_column(Integer, nullable=False)
    state_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Topic4ClaimModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_claims"
    __table_args__ = (
        UniqueConstraint("tenant_id", "claim_id"),
        UniqueConstraint("tenant_id", "verification_id", "block_id", "ordinal"),
        ForeignKeyConstraint(
            ["tenant_id", "verification_id"],
            ["topic4_verifications.tenant_id", "topic4_verifications.verification_id"],
            ondelete="RESTRICT",
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
        CheckConstraint("ordinal >= 0", name="nonnegative_ordinal"),
        CheckConstraint(
            "claim_kind IN ('TEXT', 'FORMULA', 'GRAPH', 'QUIZ', 'CODE', 'EXTENSION')",
            name="claim_kind",
        ),
        CheckConstraint("claim_sha256 ~ '^[0-9a-f]{64}$'", name="claim_sha256_format"),
        CheckConstraint("jsonb_typeof(claim_document) = 'object'", name="claim_object"),
        *topic4_record_constraints(),
        Index("ix_topic4_claims_verification_kind", "tenant_id", "verification_id", "claim_kind"),
    )

    claim_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    block_id: Mapped[str] = mapped_column(String(128), nullable=False)
    claim_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    claim_subtype: Mapped[str] = mapped_column(String(128), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4ClaimRiskModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_claim_risks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "risk_id"),
        UniqueConstraint("tenant_id", "claim_id", "policy_version"),
        ForeignKeyConstraint(
            ["tenant_id", "claim_id"],
            ["topic4_claims.tenant_id", "topic4_claims.claim_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')", name="level"),
        CheckConstraint("score BETWEEN 0 AND 1", name="score_range"),
        CheckConstraint("level <> 'CRITICAL' OR score >= 0.75", name="critical_score"),
        CheckConstraint("jsonb_typeof(risk_document) = 'object'", name="risk_object"),
        *topic4_record_constraints(),
        Index("ix_topic4_claim_risks_level", "tenant_id", "level", "created_at"),
    )

    risk_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    risk_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    risk_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4DispatchPlanModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_dispatch_plans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dispatch_plan_id"),
        UniqueConstraint("tenant_id", "verification_id", "version_cas"),
        ForeignKeyConstraint(
            ["tenant_id", "verification_id"],
            ["topic4_verifications.tenant_id", "topic4_verifications.verification_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("max_parallelism BETWEEN 1 AND 32", name="parallelism_range"),
        CheckConstraint("plan_sha256 ~ '^[0-9a-f]{64}$'", name="plan_sha256_format"),
        CheckConstraint("jsonb_typeof(plan_document) = 'object'", name="plan_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_dispatch_plans_verification", "tenant_id", "verification_id", "version_cas"
        ),
    )

    dispatch_plan_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    dispatch_plan_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    max_parallelism: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4ModuleRunModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_module_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "module_run_snapshot_id"),
        UniqueConstraint("tenant_id", "module_run_id", "run_version"),
        ForeignKeyConstraint(
            ["tenant_id", "dispatch_plan_id"],
            ["topic4_dispatch_plans.tenant_id", "topic4_dispatch_plans.dispatch_plan_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "claim_id"],
            ["topic4_claims.tenant_id", "topic4_claims.claim_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("run_version >= 1", name="positive_run_version"),
        CheckConstraint("version_cas = run_version", name="cas_matches_run_version"),
        CheckConstraint(
            "module IN ('C2_RAG', 'C3_ACADEMIC', 'C4_GRAPH', 'C5_QUIZ', 'C6_CODE', "
            "'C7_EXTENSION', 'C9_SECURITY', 'C10_PRIVACY', 'C11_COMPLIANCE')",
            name="module",
        ),
        CheckConstraint(
            "state IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'TIMED_OUT', "
            "'SKIPPED', 'CANCELLED')",
            name="state",
        ),
        CheckConstraint("attempt BETWEEN 0 AND max_attempts", name="attempt_budget"),
        CheckConstraint("max_attempts BETWEEN 1 AND 5", name="max_attempts"),
        CheckConstraint("input_sha256 ~ '^[0-9a-f]{64}$'", name="input_sha256_format"),
        CheckConstraint("jsonb_typeof(run_document) = 'object'", name="run_object"),
        *topic4_record_constraints(),
        Index("ix_topic4_module_runs_state", "tenant_id", "state", "created_at"),
        Index("ix_topic4_module_runs_claim", "tenant_id", "claim_id", "module", "run_version"),
    )

    module_run_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    module_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    run_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    dispatch_plan_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(128))
    run_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4ModuleResultModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_module_results"
    __table_args__ = (
        UniqueConstraint("tenant_id", "module_result_id"),
        UniqueConstraint("tenant_id", "module_run_id", "module_run_version"),
        ForeignKeyConstraint(
            ["tenant_id", "module_run_id", "module_run_version"],
            [
                "topic4_module_runs.tenant_id",
                "topic4_module_runs.module_run_id",
                "topic4_module_runs.run_version",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("module_run_version >= 1", name="positive_run_version"),
        CheckConstraint(
            "verdict IN ('SUPPORTED', 'PARTIALLY_SUPPORTED', 'CONTRADICTED', "
            "'INSUFFICIENT_EVIDENCE', 'UNSAFE', 'NOT_APPLICABLE', 'ERROR')",
            name="verdict",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("result_sha256 ~ '^[0-9a-f]{64}$'", name="result_sha256_format"),
        CheckConstraint("jsonb_typeof(result_document) = 'object'", name="result_object"),
        *topic4_record_constraints(),
        Index("ix_topic4_module_results_claim", "tenant_id", "claim_id", "created_at"),
    )

    module_result_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    module_result_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    module_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    module_run_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    deterministic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4ClaimVerdictModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_claim_verdicts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "claim_verdict_id"),
        UniqueConstraint("tenant_id", "verification_id", "claim_id", "version_cas"),
        ForeignKeyConstraint(
            ["tenant_id", "claim_id"],
            ["topic4_claims.tenant_id", "topic4_claims.claim_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "verdict IN ('SUPPORTED', 'PARTIALLY_SUPPORTED', 'CONTRADICTED', "
            "'INSUFFICIENT_EVIDENCE', 'UNSAFE', 'NOT_APPLICABLE', 'ERROR')",
            name="verdict",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("jsonb_typeof(verdict_document) = 'object'", name="verdict_object"),
        *topic4_record_constraints(),
        Index("ix_topic4_claim_verdicts_verification", "tenant_id", "verification_id", "verdict"),
    )

    claim_verdict_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    claim_verdict_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    non_waivable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    verdict_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4AggregationResultModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_aggregation_results"
    __table_args__ = (
        UniqueConstraint("tenant_id", "aggregation_result_id"),
        UniqueConstraint("tenant_id", "verification_id", "version_cas"),
        ForeignKeyConstraint(
            ["tenant_id", "verification_id"],
            ["topic4_verifications.tenant_id", "topic4_verifications.verification_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "decision IN ('RELEASE', 'RELEASE_WITH_DISCLOSURE', 'REVISE', "
            "'REVIEW_REQUIRED', 'BLOCK')",
            name="decision",
        ),
        CheckConstraint("overall_confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("unsafe_count >= 0", name="nonnegative_unsafe_count"),
        CheckConstraint("jsonb_typeof(result_document) = 'object'", name="result_object"),
        *topic4_record_constraints(),
        Index("ix_topic4_aggregation_verification", "tenant_id", "verification_id", "version_cas"),
    )

    aggregation_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    aggregation_result_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    overall_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    unsafe_count: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    result_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4VerificationReportModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_verification_reports"
    __table_args__ = (
        UniqueConstraint("tenant_id", "report_id"),
        UniqueConstraint("tenant_id", "verification_id", "version_cas"),
        ForeignKeyConstraint(
            ["tenant_id", "verification_id"],
            ["topic4_verifications.tenant_id", "topic4_verifications.verification_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "aggregation_result_id"],
            [
                "topic4_aggregation_results.tenant_id",
                "topic4_aggregation_results.aggregation_result_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("candidate_version >= 1", name="positive_candidate_version"),
        CheckConstraint("candidate_sha256 ~ '^[0-9a-f]{64}$'", name="candidate_sha256_format"),
        CheckConstraint("report_sha256 ~ '^[0-9a-f]{64}$'", name="report_sha256_format"),
        CheckConstraint(
            "decision IN ('RELEASE', 'RELEASE_WITH_DISCLOSURE', 'REVISE', "
            "'REVIEW_REQUIRED', 'BLOCK')",
            name="decision",
        ),
        CheckConstraint("jsonb_typeof(report_document) = 'object'", name="report_object"),
        *topic4_record_constraints(),
        Index("ix_topic4_reports_verification", "tenant_id", "verification_id", "version_cas"),
    )

    report_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    report_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregation_result_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    knowledge_base_version: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    report_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Topic4HumanReviewTaskModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_human_review_tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "review_task_snapshot_id"),
        UniqueConstraint("tenant_id", "review_task_id", "task_version"),
        ForeignKeyConstraint(
            ["tenant_id", "verification_id"],
            ["topic4_verifications.tenant_id", "topic4_verifications.verification_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("task_version >= 1", name="positive_task_version"),
        CheckConstraint("version_cas = task_version", name="cas_matches_task_version"),
        CheckConstraint(
            "state IN ('OPEN', 'CLAIMED', 'DECIDED', 'EXPIRED', 'CANCELLED')", name="state"
        ),
        CheckConstraint("risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')", name="risk_level"),
        CheckConstraint("jsonb_typeof(task_document) = 'object'", name="task_object"),
        *topic4_record_constraints(),
        Index("ix_topic4_review_tasks_state_due", "tenant_id", "state", "due_at"),
    )

    review_task_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    review_task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    task_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    assigned_role: Mapped[str] = mapped_column(String(128), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    task_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4HumanReviewDecisionModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_human_review_decisions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "review_decision_id"),
        UniqueConstraint("tenant_id", "review_task_id", "review_task_version"),
        ForeignKeyConstraint(
            ["tenant_id", "review_task_id", "review_task_version"],
            [
                "topic4_human_review_tasks.tenant_id",
                "topic4_human_review_tasks.review_task_id",
                "topic4_human_review_tasks.task_version",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "decision IN ('APPROVE', 'APPROVE_WITH_DISCLOSURE', 'REVISE', 'BLOCK')",
            name="decision",
        ),
        CheckConstraint("jsonb_typeof(decision_document) = 'object'", name="decision_object"),
        *topic4_record_constraints(),
    )

    review_decision_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    review_decision_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    review_task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    review_task_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer_subject_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    decision_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
