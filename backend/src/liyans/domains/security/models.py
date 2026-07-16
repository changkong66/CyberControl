from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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

TOPIC4_SECURITY_TABLES = ("topic4_security_findings",)


class Topic4SecurityFindingModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_security_findings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "security_finding_id"),
        UniqueConstraint(
            "tenant_id",
            "verification_id",
            "candidate_id",
            "candidate_version",
            "evidence_fingerprint_sha256",
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
            "category IN ('PROMPT_INJECTION', 'EXPOSED_CREDENTIAL', 'MALWARE', "
            "'UNSAFE_CODE', 'CONTENT_POLICY', 'CROSS_TENANT_REFERENCE', "
            "'DATA_EXFILTRATION')",
            name="category",
        ),
        CheckConstraint(
            "severity IN ('INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="severity",
        ),
        CheckConstraint(
            "disposition IN ('ALLOW', 'REDACT', 'REVIEW', 'BLOCK')", name="disposition"
        ),
        CheckConstraint(
            "evidence_fingerprint_sha256 ~ '^[0-9a-f]{64}$'",
            name="evidence_fingerprint_sha256_format",
        ),
        CheckConstraint(
            "category NOT IN ('CROSS_TENANT_REFERENCE', 'DATA_EXFILTRATION', 'MALWARE') "
            "OR (non_waivable AND disposition = 'BLOCK')",
            name="mandatory_block",
        ),
        CheckConstraint("jsonb_typeof(finding_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_security_findings_verification_severity",
            "tenant_id",
            "verification_id",
            "severity",
            "created_at",
        ),
    )

    security_finding_record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    security_finding_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    block_id: Mapped[str | None] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    disposition: Mapped[str] = mapped_column(String(16), nullable=False)
    detector: Mapped[str] = mapped_column(String(128), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    non_waivable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    finding_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
