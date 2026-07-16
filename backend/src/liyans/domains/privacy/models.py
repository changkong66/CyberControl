from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
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

TOPIC4_PRIVACY_TABLES = (
    "topic4_pii_findings",
    "topic4_tokenized_values",
    "topic4_privacy_tenant_results",
)


class Topic4PIIFindingModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_pii_findings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "pii_finding_id"),
        UniqueConstraint(
            "tenant_id",
            "verification_id",
            "candidate_id",
            "candidate_version",
            "block_id",
            "json_pointer",
            "original_value_sha256",
        ),
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
        CheckConstraint(
            "pii_type IN ('NAME', 'PHONE', 'EMAIL', 'NATIONAL_ID', 'STUDENT_ID', "
            "'ADDRESS', 'BIOMETRIC', 'CREDENTIAL', 'OTHER')",
            name="pii_type",
        ),
        CheckConstraint(
            "severity IN ('INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="severity",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("action IN ('ALLOW', 'TOKENIZE', 'REDACT', 'BLOCK')", name="action"),
        CheckConstraint(
            "original_value_sha256 ~ '^[0-9a-f]{64}$'",
            name="original_value_sha256_format",
        ),
        CheckConstraint(
            "pii_type NOT IN ('NATIONAL_ID', 'BIOMETRIC', 'CREDENTIAL') OR action <> 'ALLOW'",
            name="critical_pii_not_allowed",
        ),
        CheckConstraint("jsonb_typeof(finding_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_pii_findings_verification",
            "tenant_id",
            "verification_id",
            "severity",
            "created_at",
        ),
    )

    pii_finding_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    pii_finding_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    block_id: Mapped[str] = mapped_column(String(128), nullable=False)
    json_pointer: Mapped[str] = mapped_column(String(1024), nullable=False)
    pii_type: Mapped[str] = mapped_column(String(24), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    original_value_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    non_waivable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    finding_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4TokenizedValueModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_tokenized_values"
    __table_args__ = (
        UniqueConstraint("tenant_id", "tokenized_value_id"),
        UniqueConstraint("tenant_id", "token"),
        ForeignKeyConstraint(
            ["tenant_id", "pii_finding_id"],
            ["topic4_pii_findings.tenant_id", "topic4_pii_findings.pii_finding_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("token ~ '^tok_[A-Za-z0-9_-]{16,128}$'", name="token_format"),
        CheckConstraint(
            "original_value_sha256 ~ '^[0-9a-f]{64}$'",
            name="original_value_sha256_format",
        ),
        CheckConstraint("jsonb_typeof(token_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
    )

    tokenized_value_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tokenized_value_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    pii_finding_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    token: Mapped[str] = mapped_column(String(132), nullable=False)
    original_value_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    vault_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    key_version: Mapped[str] = mapped_column(String(128), nullable=False)
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    token_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4PrivacyTenantResultModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_privacy_tenant_results"
    __table_args__ = (
        UniqueConstraint("tenant_id", "privacy_tenant_result_id"),
        UniqueConstraint("tenant_id", "verification_id", "version_cas"),
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
        CheckConstraint("candidate_sha256 ~ '^[0-9a-f]{64}$'", name="candidate_sha256_format"),
        CheckConstraint(
            "redacted_candidate_sha256 IS NULL OR redacted_candidate_sha256 ~ '^[0-9a-f]{64}$'",
            name="redacted_sha256_format",
        ),
        CheckConstraint(
            "verdict IN ('SUPPORTED', 'PARTIALLY_SUPPORTED', 'CONTRADICTED', "
            "'INSUFFICIENT_EVIDENCE', 'UNSAFE', 'NOT_APPLICABLE', 'ERROR')",
            name="verdict",
        ),
        CheckConstraint(
            "tenant_boundary_valid OR verdict = 'UNSAFE'", name="invalid_boundary_unsafe"
        ),
        CheckConstraint("jsonb_typeof(pii_finding_ids) = 'array'", name="pii_findings_array"),
        CheckConstraint("jsonb_typeof(tokenized_value_ids) = 'array'", name="tokens_array"),
        CheckConstraint(
            "redacted_candidate_artifact IS NULL OR "
            "jsonb_typeof(redacted_candidate_artifact) = 'object'",
            name="redacted_artifact_object",
        ),
        CheckConstraint(
            "(redacted_candidate_artifact IS NULL) = (redacted_candidate_sha256 IS NULL)",
            name="redacted_artifact_pair",
        ),
        CheckConstraint("jsonb_typeof(result_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
    )

    privacy_tenant_result_record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    privacy_tenant_result_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_boundary_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pii_finding_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    tokenized_value_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    redacted_candidate_artifact: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    redacted_candidate_sha256: Mapped[str | None] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    result_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
