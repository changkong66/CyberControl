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

TOPIC4_RELEASE_TABLES = (
    "topic4_release_authorizations",
    "topic4_release_authorization_consumptions",
    "topic4_publication_batches",
    "topic4_public_stream_events",
)


class Topic4ReleaseAuthorizationModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_release_authorizations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "authorization_id"),
        UniqueConstraint(
            "tenant_id", "candidate_id", "candidate_version", "candidate_sha256", "report_sha256"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "verification_id"],
            ["topic4_verifications.tenant_id", "topic4_verifications.verification_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "report_id"],
            ["topic4_verification_reports.tenant_id", "topic4_verification_reports.report_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("candidate_version >= 1", name="positive_candidate_version"),
        CheckConstraint("candidate_sha256 ~ '^[0-9a-f]{64}$'", name="candidate_sha256_format"),
        CheckConstraint("report_sha256 ~ '^[0-9a-f]{64}$'", name="report_sha256_format"),
        CheckConstraint("release_mode IN ('FULL', 'FULL_WITH_DISCLOSURE')", name="release_mode"),
        CheckConstraint("expires_at > issued_at", name="expiry_window"),
        CheckConstraint("one_time_use", name="one_time_use_required"),
        CheckConstraint("jsonb_typeof(allowed_block_ids) = 'array'", name="blocks_array"),
        CheckConstraint("jsonb_typeof(authorization_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index("ix_topic4_release_authorizations_expiry", "tenant_id", "expires_at"),
    )

    authorization_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    authorization_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    report_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    release_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    allowed_block_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    one_time_use: Mapped[bool] = mapped_column(nullable=False)
    authorization_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4ReleaseAuthorizationConsumptionModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_release_authorization_consumptions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "consumption_id"),
        UniqueConstraint("tenant_id", "authorization_id"),
        ForeignKeyConstraint(
            ["tenant_id", "authorization_id"],
            [
                "topic4_release_authorizations.tenant_id",
                "topic4_release_authorizations.authorization_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'", name="request_sha256_format"),
        CheckConstraint("jsonb_typeof(consumption_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
    )

    consumption_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    consumption_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    authorization_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    publication_batch_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    consumed_by_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumption_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4PublicationBatchModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_publication_batches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "publication_batch_snapshot_id"),
        UniqueConstraint("tenant_id", "publication_batch_id", "batch_version"),
        ForeignKeyConstraint(
            ["tenant_id", "authorization_id"],
            [
                "topic4_release_authorizations.tenant_id",
                "topic4_release_authorizations.authorization_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("batch_version >= 1", name="positive_batch_version"),
        CheckConstraint("version_cas = batch_version", name="cas_matches_batch_version"),
        CheckConstraint("state IN ('PENDING', 'COMMITTED', 'FAILED')", name="state"),
        CheckConstraint("candidate_version >= 1", name="positive_candidate_version"),
        CheckConstraint("candidate_sha256 ~ '^[0-9a-f]{64}$'", name="candidate_sha256_format"),
        CheckConstraint("jsonb_typeof(batch_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_publication_batches_authorization",
            "tenant_id",
            "authorization_id",
            "batch_version",
        ),
    )

    publication_batch_snapshot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    publication_batch_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    batch_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    authorization_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    report_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    batch_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Topic4PublicStreamEventModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_public_stream_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "public_event_id"),
        UniqueConstraint("tenant_id", "stream_id", "sequence"),
        ForeignKeyConstraint(
            ["tenant_id", "publication_batch_id", "publication_batch_version"],
            [
                "topic4_publication_batches.tenant_id",
                "topic4_publication_batches.publication_batch_id",
                "topic4_publication_batches.batch_version",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("publication_batch_version >= 1", name="positive_batch_version"),
        CheckConstraint("sequence >= 0", name="nonnegative_sequence"),
        CheckConstraint("payload_sha256 ~ '^[0-9a-f]{64}$'", name="payload_sha256_format"),
        CheckConstraint("jsonb_typeof(event_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index("ix_topic4_public_stream_order", "tenant_id", "stream_id", "sequence"),
        Index("ix_topic4_public_stream_emitted", "tenant_id", "emitted_at"),
    )

    public_event_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    public_event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    publication_batch_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    publication_batch_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    authorization_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    stream_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    event_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    emitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
