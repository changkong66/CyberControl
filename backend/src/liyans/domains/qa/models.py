from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
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

TOPIC4_QA_TABLES = (
    "topic4_acceptance_reports",
    "topic4_acceptance_gate_results",
)


class Topic4SystemAcceptanceReportModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_acceptance_reports"
    __table_args__ = (
        UniqueConstraint("tenant_id", "system_acceptance_report_id"),
        UniqueConstraint("tenant_id", "build_commit_sha256", "build_version"),
        CheckConstraint("build_commit_sha256 ~ '^[0-9a-f]{64}$'", name="commit_sha256_format"),
        CheckConstraint("python_coverage_percent BETWEEN 0 AND 100", name="coverage_range"),
        CheckConstraint("concurrent_verifications >= 0", name="nonnegative_concurrency"),
        CheckConstraint("retrieval_p95_ms >= 0", name="nonnegative_retrieval_p95"),
        CheckConstraint("publication_p95_ms >= 0", name="nonnegative_publication_p95"),
        CheckConstraint(
            "cross_tenant_leaks >= 0 AND authorization_replay_successes >= 0 AND "
            "critical_vulnerabilities >= 0 AND high_vulnerabilities >= 0 AND "
            "open_p0_defects >= 0 AND open_p1_defects >= 0 AND flaky_core_tests >= 0",
            name="nonnegative_redlines",
        ),
        CheckConstraint("decision IN ('ACCEPTED', 'REJECTED')", name="decision"),
        CheckConstraint("report_sha256 ~ '^[0-9a-f]{64}$'", name="report_sha256_format"),
        CheckConstraint("jsonb_typeof(report_artifact) = 'object'", name="artifact_object"),
        CheckConstraint("jsonb_typeof(report_document) = 'object'", name="document_object"),
        CheckConstraint(
            "decision <> 'ACCEPTED' OR (python_coverage_percent >= 90 AND "
            "concurrent_verifications >= 200 AND retrieval_p95_ms <= 200 AND "
            "publication_p95_ms <= 300 AND cross_tenant_leaks = 0 AND "
            "authorization_replay_successes = 0 AND critical_vulnerabilities = 0 AND "
            "high_vulnerabilities = 0 AND open_p0_defects = 0 AND open_p1_defects = 0 AND "
            "flaky_core_tests = 0)",
            name="accepted_redlines",
        ),
        *topic4_record_constraints(),
        Index("ix_topic4_acceptance_reports_build", "tenant_id", "created_at"),
    )

    acceptance_report_record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    system_acceptance_report_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    build_commit_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    build_version: Mapped[str] = mapped_column(String(128), nullable=False)
    python_coverage_percent: Mapped[float] = mapped_column(Float, nullable=False)
    concurrent_verifications: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieval_p95_ms: Mapped[float] = mapped_column(Float, nullable=False)
    publication_p95_ms: Mapped[float] = mapped_column(Float, nullable=False)
    cross_tenant_leaks: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_replay_successes: Mapped[int] = mapped_column(Integer, nullable=False)
    critical_vulnerabilities: Mapped[int] = mapped_column(Integer, nullable=False)
    high_vulnerabilities: Mapped[int] = mapped_column(Integer, nullable=False)
    open_p0_defects: Mapped[int] = mapped_column(Integer, nullable=False)
    open_p1_defects: Mapped[int] = mapped_column(Integer, nullable=False)
    flaky_core_tests: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    report_artifact: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    report_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4AcceptanceGateResultModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_acceptance_gate_results"
    __table_args__ = (
        UniqueConstraint("tenant_id", "acceptance_gate_result_id"),
        UniqueConstraint("tenant_id", "system_acceptance_report_id", "gate_code"),
        ForeignKeyConstraint(
            ["tenant_id", "system_acceptance_report_id"],
            [
                "topic4_acceptance_reports.tenant_id",
                "topic4_acceptance_reports.system_acceptance_report_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("gate_code ~ '^G([0-9]|1[0-2])$'", name="gate_code_format"),
        CheckConstraint("status IN ('PASSED', 'FAILED', 'SKIPPED')", name="status"),
        CheckConstraint("evidence_sha256 ~ '^[0-9a-f]{64}$'", name="evidence_sha256_format"),
        CheckConstraint("jsonb_typeof(metric_values) = 'object'", name="metrics_object"),
        CheckConstraint("jsonb_typeof(evidence_artifact) = 'object'", name="artifact_object"),
        CheckConstraint("jsonb_typeof(failure_codes) = 'array'", name="failures_array"),
        CheckConstraint("jsonb_typeof(gate_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
    )

    acceptance_gate_result_record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    acceptance_gate_result_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    system_acceptance_report_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    gate_code: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    metric_values: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    evidence_artifact: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    failure_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    gate_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
