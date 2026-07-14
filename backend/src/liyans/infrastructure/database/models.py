from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

TENANT_SCOPED_TABLES = (
    "tenants",
    "artifacts",
    "idempotency_records",
    "outbox_messages",
    "audit_events",
    "sse_events",
)


class TenantStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEPROVISIONED = "DEPROVISIONED"


class ArtifactStatus(StrEnum):
    STAGED = "STAGED"
    VERIFIED = "VERIFIED"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    DELETED = "DELETED"


class IdempotencyStatus(StrEnum):
    BUFFERED = "BUFFERED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    PUBLISHED = "PUBLISHED"
    DEAD = "DEAD"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TenantModel(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'DEPROVISIONED')",
            name="status",
        ),
        CheckConstraint("version >= 1", name="positive_version"),
        CheckConstraint(
            "(oidc_issuer IS NULL) = (oidc_tenant_claim IS NULL)",
            name="oidc_binding_pair",
        ),
        CheckConstraint(
            "slug = lower(slug) AND slug ~ '^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$'",
            name="canonical_slug",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'ACTIVE'"))
    oidc_issuer: Mapped[str | None] = mapped_column(String(512))
    oidc_tenant_claim: Mapped[str | None] = mapped_column(String(256))
    settings_document: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ArtifactModel(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "storage_namespace", "object_key"),
        CheckConstraint(
            "status IN ('STAGED', 'VERIFIED', 'PUBLISHED', 'REJECTED', 'SUPERSEDED', 'DELETED')",
            name="status",
        ),
        CheckConstraint(
            "resource_type IN ('Lecturer_Doc', 'MindMap', 'Gradient_Quiz', "
            "'Simulation_Code', 'Extension_Material')",
            name="resource_type",
        ),
        CheckConstraint("artifact_version >= 1", name="positive_version"),
        CheckConstraint("byte_size >= 1", name="positive_byte_size"),
        CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="sha256_format",
        ),
        CheckConstraint(
            "(candidate_id IS NULL) = (candidate_version IS NULL)",
            name="candidate_version_pair",
        ),
        CheckConstraint(
            "candidate_version IS NULL OR candidate_version >= 1",
            name="candidate_version_positive",
        ),
        CheckConstraint("jsonb_typeof(provenance) = 'object'", name="provenance_object"),
        Index("ix_artifacts_tenant_resource_created", "tenant_id", "resource_type", "created_at"),
        Index(
            "ix_artifacts_tenant_candidate_version",
            "tenant_id",
            "candidate_id",
            "candidate_version",
        ),
    )

    artifact_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'STAGED'"))
    storage_namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    content_encoding: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'identity'")
    )
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_envelope_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    blueprint_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    blueprint_version: Mapped[str | None] = mapped_column(String(64))
    candidate_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    candidate_version: Mapped[int | None] = mapped_column(Integer)
    block_id: Mapped[str | None] = mapped_column(String(128))
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_by_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyRecordModel(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "idempotency_key"),
        CheckConstraint(
            "state IN ('BUFFERED', 'PROCESSING', 'COMPLETED')",
            name="state",
        ),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="request_digest_format"),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name="lease_pair",
        ),
        CheckConstraint(
            "response_status_code IS NULL OR response_status_code BETWEEN 100 AND 599",
            name="response_status_code",
        ),
        CheckConstraint(
            "result_payload IS NULL OR jsonb_typeof(result_payload) = 'object'",
            name="result_payload_object",
        ),
        Index("ix_idempotency_records_expires_at", "expires_at"),
    )

    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'BUFFERED'")
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_status_code: Mapped[int | None] = mapped_column(SmallInteger)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OutboxMessageModel(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "envelope_id"),
        UniqueConstraint("tenant_id", "partition_key", "sequence"),
        CheckConstraint(
            "state IN ('PENDING', 'CLAIMED', 'PUBLISHED', 'DEAD')",
            name="state",
        ),
        CheckConstraint("sequence >= 0", name="nonnegative_sequence"),
        CheckConstraint("attempts >= 0 AND attempts <= max_attempts", name="attempt_budget"),
        CheckConstraint("max_attempts BETWEEN 1 AND 16", name="max_attempts"),
        CheckConstraint("envelope_sha256 ~ '^[0-9a-f]{64}$'", name="envelope_sha256_format"),
        CheckConstraint("jsonb_typeof(envelope) = 'object'", name="envelope_object"),
        CheckConstraint(
            "(claimed_by IS NULL AND claimed_at IS NULL AND claim_expires_at IS NULL) OR "
            "(claimed_by IS NOT NULL AND claimed_at IS NOT NULL AND claim_expires_at IS NOT NULL)",
            name="claim_fields",
        ),
        CheckConstraint(
            "state <> 'PUBLISHED' OR published_at IS NOT NULL",
            name="published_timestamp",
        ),
        Index(
            "ix_outbox_messages_dispatch",
            "state",
            "available_at",
            "created_at",
            postgresql_where=text("state IN ('PENDING', 'CLAIMED')"),
        ),
        Index("ix_outbox_messages_tenant_created", "tenant_id", "created_at"),
    )

    outbox_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    envelope_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    message_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    partition_key: Mapped[str] = mapped_column(String(256), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    aggregate_type: Mapped[str | None] = mapped_column(String(128))
    aggregate_id: Mapped[str | None] = mapped_column(String(256))
    aggregate_version: Mapped[int | None] = mapped_column(BigInteger)
    envelope_document: Mapped[dict[str, Any]] = mapped_column("envelope", JSONB, nullable=False)
    envelope_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'PENDING'"))
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'NORMAL'")
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("3")
    )
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(128))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuditEventModel(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sequence"),
        UniqueConstraint("tenant_id", "event_hash"),
        CheckConstraint("sequence >= 0", name="nonnegative_sequence"),
        CheckConstraint("previous_hash ~ '^[0-9a-f]{64}$'", name="previous_hash_format"),
        CheckConstraint("event_hash ~ '^[0-9a-f]{64}$'", name="event_hash_format"),
        CheckConstraint("hash_algorithm = 'SHA-256'", name="hash_algorithm"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        Index("ix_audit_events_tenant_occurred", "tenant_id", "occurred_at"),
        Index("ix_audit_events_trace_id", "trace_id"),
    )

    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    target_ref: Mapped[str | None] = mapped_column(String(512))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    envelope_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash_algorithm: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'SHA-256'")
    )
    signing_key_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SSEEventModel(Base):
    __tablename__ = "sse_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sequence"),
        CheckConstraint("sequence >= 0", name="nonnegative_sequence"),
        CheckConstraint("data_sha256 ~ '^[0-9a-f]{64}$'", name="data_sha256_format"),
        CheckConstraint("jsonb_typeof(data) = 'object'", name="data_object"),
        CheckConstraint("expires_at > emitted_at", name="retention_window"),
        Index("ix_sse_events_tenant_emitted", "tenant_id", "emitted_at"),
        Index("ix_sse_events_tenant_stream_sequence", "tenant_id", "stream_id", "sequence"),
        Index("ix_sse_events_expires_at", "expires_at"),
    )

    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stream_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    session_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    correlation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    envelope_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    data_document: Mapped[dict[str, Any]] = mapped_column("data", JSONB, nullable=False)
    data_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    emitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
