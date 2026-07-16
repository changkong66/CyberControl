from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
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

TOPIC4_REVISION_TABLES = (
    "topic4_revision_cycles",
    "topic4_revision_plans",
    "topic4_revision_patches",
)


class Topic4RevisionCycleModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_revision_cycles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "revision_cycle_snapshot_id"),
        UniqueConstraint("tenant_id", "revision_cycle_id", "cycle_version"),
        UniqueConstraint("tenant_id", "verification_id", "revision_round", "cycle_version"),
        ForeignKeyConstraint(
            ["tenant_id", "verification_id"],
            ["topic4_verifications.tenant_id", "topic4_verifications.verification_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "candidate_id", "base_candidate_version"],
            [
                "topic3_generated_candidates.tenant_id",
                "topic3_generated_candidates.candidate_id",
                "topic3_generated_candidates.candidate_version",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("cycle_version >= 1", name="positive_cycle_version"),
        CheckConstraint("version_cas = cycle_version", name="cas_matches_cycle_version"),
        CheckConstraint("revision_round BETWEEN 1 AND 2", name="revision_round"),
        CheckConstraint(
            "state IN ('PLANNED', 'LOCKED', 'GENERATING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="state",
        ),
        CheckConstraint("base_candidate_sha256 ~ '^[0-9a-f]{64}$'", name="candidate_sha256_format"),
        CheckConstraint("lock_expires_at > created_at", name="lock_expiry"),
        CheckConstraint("jsonb_typeof(cycle_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_revision_cycles_verification",
            "tenant_id",
            "verification_id",
            "revision_round",
            "cycle_version",
        ),
    )

    revision_cycle_snapshot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    revision_cycle_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    cycle_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    parent_verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    base_candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    base_candidate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_round: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    lock_token: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    lock_owner: Mapped[str] = mapped_column(String(128), nullable=False)
    lock_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cycle_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4RevisionPlanModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_revision_plans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "revision_plan_id"),
        UniqueConstraint("tenant_id", "revision_cycle_id", "version_cas"),
        ForeignKeyConstraint(
            ["tenant_id", "revision_cycle_id", "revision_cycle_version"],
            [
                "topic4_revision_cycles.tenant_id",
                "topic4_revision_cycles.revision_cycle_id",
                "topic4_revision_cycles.cycle_version",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("revision_cycle_version >= 1", name="positive_cycle_version"),
        CheckConstraint("revision_round BETWEEN 1 AND 2", name="revision_round"),
        CheckConstraint("base_candidate_sha256 ~ '^[0-9a-f]{64}$'", name="candidate_sha256_format"),
        CheckConstraint("plan_sha256 ~ '^[0-9a-f]{64}$'", name="plan_sha256_format"),
        CheckConstraint("jsonb_typeof(plan_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
    )

    revision_plan_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    revision_plan_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    revision_cycle_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    revision_cycle_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    base_candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    base_candidate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_round: Mapped[int] = mapped_column(Integer, nullable=False)
    target_agent: Mapped[str] = mapped_column(String(24), nullable=False)
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4RevisionPatchModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_revision_patches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "revision_patch_id"),
        UniqueConstraint("tenant_id", "revision_plan_id", "block_id"),
        ForeignKeyConstraint(
            ["tenant_id", "revision_plan_id"],
            ["topic4_revision_plans.tenant_id", "topic4_revision_plans.revision_plan_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("operation IN ('REPLACE_BLOCK', 'REMOVE_BLOCK')", name="operation"),
        CheckConstraint("base_block_sha256 ~ '^[0-9a-f]{64}$'", name="base_sha256_format"),
        CheckConstraint(
            "replacement_sha256 IS NULL OR replacement_sha256 ~ '^[0-9a-f]{64}$'",
            name="replacement_sha256_format",
        ),
        CheckConstraint(
            "(operation = 'REPLACE_BLOCK' AND replacement_sha256 IS NOT NULL) OR "
            "(operation = 'REMOVE_BLOCK' AND replacement_sha256 IS NULL)",
            name="replacement_semantics",
        ),
        CheckConstraint("jsonb_typeof(patch_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
    )

    revision_patch_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    revision_patch_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    revision_plan_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    block_id: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(24), nullable=False)
    base_block_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    replacement_sha256: Mapped[str | None] = mapped_column(String(64))
    patch_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
