from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from liyans.infrastructure.database.models import Base

IDENTITY_TENANT_TABLES = (
    "identity_accounts",
    "identity_registration_snapshots",
    "identity_verification_challenges",
    "identity_verification_rate_limits",
    "identity_consent_records",
    "identity_reconciliation_jobs",
)

IDENTITY_APPEND_ONLY_TABLES = (
    "identity_registration_snapshots",
    "identity_consent_records",
)


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class ContactChannel(StrEnum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"


class ChallengePurpose(StrEnum):
    REGISTER = "REGISTER"
    CHANGE_EMAIL = "CHANGE_EMAIL"
    CHANGE_PHONE = "CHANGE_PHONE"
    RECOVERY = "RECOVERY"


class ChallengeState(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    LOCKED = "LOCKED"


class RegistrationState(StrEnum):
    KEYCLOAK_PENDING = "KEYCLOAK_PENDING"
    PROJECTION_PENDING = "PROJECTION_PENDING"
    COMPLETED = "COMPLETED"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    FAILED = "FAILED"


class ReconciliationState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IdentityAccountModel(Base):
    __tablename__ = "identity_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "account_id"),
        UniqueConstraint("tenant_id", "oidc_subject"),
        UniqueConstraint("email_lookup_digest"),
        UniqueConstraint("phone_lookup_digest"),
        CheckConstraint(
            "status IN ('ACTIVE', 'DISABLED', 'RECONCILIATION_REQUIRED')",
            name="status",
        ),
        CheckConstraint(
            "preferred_locale IN ('zh-CN', 'zh-TW', 'en-US')",
            name="preferred_locale",
        ),
        CheckConstraint("profile_version >= 1", name="positive_profile_version"),
        CheckConstraint(
            "(email_ciphertext IS NULL) = (email_lookup_digest IS NULL)",
            name="email_storage_pair",
        ),
        CheckConstraint(
            "(phone_ciphertext IS NULL) = (phone_lookup_digest IS NULL)",
            name="phone_storage_pair",
        ),
        CheckConstraint(
            "NOT email_verified OR email_ciphertext IS NOT NULL",
            name="verified_email_present",
        ),
        CheckConstraint(
            "NOT phone_verified OR phone_ciphertext IS NOT NULL",
            name="verified_phone_present",
        ),
        CheckConstraint(
            "email_lookup_digest IS NULL OR email_lookup_digest ~ '^[0-9a-f]{64}$'",
            name="email_lookup_digest_format",
        ),
        CheckConstraint(
            "phone_lookup_digest IS NULL OR phone_lookup_digest ~ '^[0-9a-f]{64}$'",
            name="phone_lookup_digest_format",
        ),
        Index("ix_identity_accounts_tenant_status", "tenant_id", "status", "created_at"),
    )

    account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    oidc_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    preferred_locale: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'zh-CN'")
    )
    email_ciphertext: Mapped[str | None] = mapped_column(String(4096))
    email_lookup_digest: Mapped[str | None] = mapped_column(String(64))
    email_hint: Mapped[str | None] = mapped_column(String(320))
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    phone_ciphertext: Mapped[str | None] = mapped_column(String(4096))
    phone_lookup_digest: Mapped[str | None] = mapped_column(String(64))
    phone_hint: Mapped[str | None] = mapped_column(String(32))
    phone_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'ACTIVE'"))
    disabled_reason_code: Mapped[str | None] = mapped_column(String(128))
    profile_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IdentityRegistrationSnapshotModel(Base):
    __tablename__ = "identity_registration_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "registration_id", "registration_version"),
        UniqueConstraint("tenant_id", "idempotency_key_digest", "registration_version"),
        CheckConstraint(
            "channel IN ('EMAIL', 'PHONE')",
            name="channel",
        ),
        CheckConstraint(
            "state IN ('KEYCLOAK_PENDING', 'PROJECTION_PENDING', 'COMPLETED', "
            "'COMPENSATION_REQUIRED', 'FAILED')",
            name="state",
        ),
        CheckConstraint("registration_version >= 1", name="positive_registration_version"),
        CheckConstraint("identifier_digest ~ '^[0-9a-f]{64}$'", name="identifier_digest_format"),
        CheckConstraint(
            "idempotency_key_digest ~ '^[0-9a-f]{64}$'",
            name="idempotency_key_digest_format",
        ),
        CheckConstraint("record_sha256 ~ '^[0-9a-f]{64}$'", name="record_sha256_format"),
        CheckConstraint("jsonb_typeof(state_document) = 'object'", name="state_document_object"),
        CheckConstraint("immutable", name="immutable_record"),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["identity_accounts.tenant_id", "identity_accounts.account_id"],
            ondelete="RESTRICT",
        ),
        Index(
            "ix_identity_registration_snapshots_latest",
            "tenant_id",
            "registration_id",
            "registration_version",
        ),
        Index(
            "ix_identity_registration_snapshots_idempotency",
            "tenant_id",
            "idempotency_key_digest",
            "registration_version",
        ),
    )

    registration_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    registration_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    registration_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    identifier_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    keycloak_user_id: Mapped[str | None] = mapped_column(String(256))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    state_document: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    record_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IdentityVerificationChallengeModel(Base):
    __tablename__ = "identity_verification_challenges"
    __table_args__ = (
        CheckConstraint("channel IN ('EMAIL', 'PHONE')", name="channel"),
        CheckConstraint(
            "purpose IN ('REGISTER', 'CHANGE_EMAIL', 'CHANGE_PHONE', 'RECOVERY')",
            name="purpose",
        ),
        CheckConstraint(
            "state IN ('PENDING', 'VERIFIED', 'CONSUMED', 'EXPIRED', 'LOCKED')",
            name="state",
        ),
        CheckConstraint("identifier_digest ~ '^[0-9a-f]{64}$'", name="identifier_digest_format"),
        CheckConstraint("code_digest ~ '^[0-9a-f]{64}$'", name="code_digest_format"),
        CheckConstraint(
            "request_fingerprint_digest ~ '^[0-9a-f]{64}$'",
            name="request_fingerprint_digest_format",
        ),
        CheckConstraint("attempt_count >= 0", name="nonnegative_attempt_count"),
        CheckConstraint("max_attempts BETWEEN 1 AND 20", name="max_attempts"),
        CheckConstraint("send_count BETWEEN 1 AND 20", name="send_count"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        Index(
            "ix_identity_verification_challenges_lookup",
            "tenant_id",
            "channel",
            "identifier_digest",
            "created_at",
        ),
        Index("ix_identity_verification_challenges_expiry", "tenant_id", "expires_at"),
    )

    challenge_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    registration_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    account_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    identifier_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    delivery_hint: Mapped[str] = mapped_column(String(320), nullable=False)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'PENDING'"))
    attempt_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    send_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdentityVerificationRateLimitModel(Base):
    __tablename__ = "identity_verification_rate_limits"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dimension_kind", "dimension_digest", "window_started_at"),
        CheckConstraint(
            "dimension_kind IN ('IDENTIFIER', 'IP', 'DEVICE')",
            name="dimension_kind",
        ),
        CheckConstraint("dimension_digest ~ '^[0-9a-f]{64}$'", name="dimension_digest_format"),
        CheckConstraint("window_seconds BETWEEN 1 AND 86400", name="window_seconds"),
        CheckConstraint("request_count >= 1", name="positive_request_count"),
        Index(
            "ix_identity_verification_rate_limits_active",
            "tenant_id",
            "dimension_kind",
            "dimension_digest",
            "updated_at",
        ),
    )

    rate_limit_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    dimension_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    dimension_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdentityConsentRecordModel(Base):
    __tablename__ = "identity_consent_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "consent_id"),
        CheckConstraint(
            "policy_type IN ('PRIVACY_POLICY', 'TERMS_OF_SERVICE')",
            name="policy_type",
        ),
        CheckConstraint("record_sha256 ~ '^[0-9a-f]{64}$'", name="record_sha256_format"),
        CheckConstraint(
            "jsonb_typeof(consent_document) = 'object'", name="consent_document_object"
        ),
        CheckConstraint("immutable", name="immutable_record"),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["identity_accounts.tenant_id", "identity_accounts.account_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_identity_consent_records_account", "tenant_id", "account_id", "accepted_at"),
    )

    consent_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    consent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    registration_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    policy_type: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actor_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consent_document: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    record_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IdentityReconciliationJobModel(Base):
    __tablename__ = "identity_reconciliation_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "correlation_id", "operation"),
        CheckConstraint(
            "operation IN ('FINALIZE_PROJECTION', 'DELETE_KEYCLOAK_USER', "
            "'UPDATE_KEYCLOAK_USER', 'SET_KEYCLOAK_STATUS')",
            name="operation",
        ),
        CheckConstraint(
            "registration_id IS NOT NULL OR account_id IS NOT NULL",
            name="target_present",
        ),
        CheckConstraint(
            "state IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')",
            name="state",
        ),
        CheckConstraint(
            "(state = 'RUNNING' AND claim_token IS NOT NULL AND claimed_by IS NOT NULL) "
            "OR (state <> 'RUNNING' AND claim_token IS NULL AND claimed_by IS NULL)",
            name="claim_ownership",
        ),
        CheckConstraint("attempt_count >= 0", name="nonnegative_attempt_count"),
        CheckConstraint("max_attempts BETWEEN 1 AND 64", name="max_attempts"),
        CheckConstraint("jsonb_typeof(job_document) = 'object'", name="job_document_object"),
        Index(
            "ix_identity_reconciliation_jobs_due",
            "tenant_id",
            "state",
            "next_attempt_at",
        ),
        Index(
            "uq_identity_reconciliation_jobs_active_account",
            "tenant_id",
            "account_id",
            unique=True,
            postgresql_where=text(
                "account_id IS NOT NULL "
                "AND operation <> 'FINALIZE_PROJECTION' "
                "AND state IN ('PENDING', 'RUNNING')"
            ),
        ),
    )

    reconciliation_job_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    correlation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    registration_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    account_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    keycloak_user_id: Mapped[str | None] = mapped_column(String(256))
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    claim_token: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    claimed_by: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'PENDING'"))
    attempt_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("8")
    )
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    job_document: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
