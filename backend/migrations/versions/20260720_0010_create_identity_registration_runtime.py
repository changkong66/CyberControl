"""Create identity registration and account projection runtime.

Revision ID: 20260720_0010
Revises: 20260716_0009
Create Date: 2026-07-20 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260720_0010"
down_revision: str | Sequence[str] | None = "20260716_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IDENTITY_TABLES = (
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


def _install_tenant_policy(table_name: str) -> None:
    tenant_expression = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')"
    op.execute(sa.text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            f"CREATE POLICY {table_name}_tenant_isolation ON {table_name} "
            f"USING ({tenant_expression}) WITH CHECK ({tenant_expression})"
        )
    )


def _install_append_only_trigger(table_name: str) -> None:
    op.execute(
        sa.text(
            f"CREATE TRIGGER trg_{table_name}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_identity_append_only_mutation()"
        )
    )


def _grant_runtime_privileges() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'liyans_app') THEN
                    EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE '
                        || 'identity_accounts, identity_registration_snapshots, '
                        || 'identity_verification_challenges, '
                        || 'identity_verification_rate_limits, identity_consent_records, '
                        || 'identity_reconciliation_jobs FROM liyans_app';
                    EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE '
                        || 'identity_accounts, identity_verification_challenges, '
                        || 'identity_verification_rate_limits, identity_reconciliation_jobs '
                        || 'TO liyans_app';
                    EXECUTE 'GRANT SELECT, INSERT ON TABLE '
                        || 'identity_registration_snapshots, identity_consent_records '
                        || 'TO liyans_app';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = 'liyans_identity_reconciler'
                ) THEN
                    EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE identity_reconciliation_jobs '
                        || 'FROM liyans_identity_reconciler';
                    EXECUTE 'GRANT SELECT (tenant_id) ON TABLE identity_reconciliation_jobs '
                        || 'TO liyans_identity_reconciler';
                END IF;
            END
            $$
            """
        )
    )


def upgrade() -> None:
    op.create_table(
        "identity_accounts",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("oidc_subject", sa.String(length=256), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "preferred_locale",
            sa.String(length=16),
            server_default=sa.text("'zh-CN'"),
            nullable=False,
        ),
        sa.Column("email_ciphertext", sa.String(length=4096), nullable=True),
        sa.Column("email_lookup_digest", sa.String(length=64), nullable=True),
        sa.Column("email_hint", sa.String(length=320), nullable=True),
        sa.Column("email_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("phone_ciphertext", sa.String(length=4096), nullable=True),
        sa.Column("phone_lookup_digest", sa.String(length=64), nullable=True),
        sa.Column("phone_hint", sa.String(length=32), nullable=True),
        sa.Column("phone_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'ACTIVE'"), nullable=False
        ),
        sa.Column("disabled_reason_code", sa.String(length=128), nullable=True),
        sa.Column("profile_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'DISABLED', 'RECONCILIATION_REQUIRED')",
            name=op.f("ck_identity_accounts_status"),
        ),
        sa.CheckConstraint(
            "preferred_locale IN ('zh-CN', 'zh-TW', 'en-US')",
            name=op.f("ck_identity_accounts_preferred_locale"),
        ),
        sa.CheckConstraint(
            "profile_version >= 1",
            name=op.f("ck_identity_accounts_positive_profile_version"),
        ),
        sa.CheckConstraint(
            "(email_ciphertext IS NULL) = (email_lookup_digest IS NULL)",
            name=op.f("ck_identity_accounts_email_storage_pair"),
        ),
        sa.CheckConstraint(
            "(phone_ciphertext IS NULL) = (phone_lookup_digest IS NULL)",
            name=op.f("ck_identity_accounts_phone_storage_pair"),
        ),
        sa.CheckConstraint(
            "NOT email_verified OR email_ciphertext IS NOT NULL",
            name=op.f("ck_identity_accounts_verified_email_present"),
        ),
        sa.CheckConstraint(
            "NOT phone_verified OR phone_ciphertext IS NOT NULL",
            name=op.f("ck_identity_accounts_verified_phone_present"),
        ),
        sa.CheckConstraint(
            "email_lookup_digest IS NULL OR email_lookup_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_identity_accounts_email_lookup_digest_format"),
        ),
        sa.CheckConstraint(
            "phone_lookup_digest IS NULL OR phone_lookup_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_identity_accounts_phone_lookup_digest_format"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_identity_accounts_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("account_id", name=op.f("pk_identity_accounts")),
        sa.UniqueConstraint(
            "tenant_id", "account_id", name=op.f("uq_identity_accounts_tenant_id_account_id")
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "oidc_subject",
            name=op.f("uq_identity_accounts_tenant_id_oidc_subject"),
        ),
        sa.UniqueConstraint(
            "email_lookup_digest",
            name=op.f("uq_identity_accounts_email_lookup_digest"),
        ),
        sa.UniqueConstraint(
            "phone_lookup_digest",
            name=op.f("uq_identity_accounts_phone_lookup_digest"),
        ),
    )
    op.create_index(
        "ix_identity_accounts_tenant_status",
        "identity_accounts",
        ["tenant_id", "status", "created_at"],
    )

    op.create_table(
        "identity_registration_snapshots",
        sa.Column("registration_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("registration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("registration_version", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("identifier_digest", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key_digest", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("keycloak_user_id", sa.String(length=256), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column(
            "state_document",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("record_sha256", sa.String(length=64), nullable=False),
        sa.Column("immutable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "channel IN ('EMAIL', 'PHONE')",
            name=op.f("ck_identity_registration_snapshots_channel"),
        ),
        sa.CheckConstraint(
            "state IN ('KEYCLOAK_PENDING', 'PROJECTION_PENDING', 'COMPLETED', "
            "'COMPENSATION_REQUIRED', 'FAILED')",
            name=op.f("ck_identity_registration_snapshots_state"),
        ),
        sa.CheckConstraint(
            "registration_version >= 1",
            name=op.f("ck_identity_registration_snapshots_positive_registration_version"),
        ),
        sa.CheckConstraint(
            "identifier_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_identity_registration_snapshots_identifier_digest_format"),
        ),
        sa.CheckConstraint(
            "idempotency_key_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_identity_registration_snapshots_idempotency_key_digest_format"),
        ),
        sa.CheckConstraint(
            "record_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_identity_registration_snapshots_record_sha256_format"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(state_document) = 'object'",
            name=op.f("ck_identity_registration_snapshots_state_document_object"),
        ),
        sa.CheckConstraint(
            "immutable",
            name=op.f("ck_identity_registration_snapshots_immutable_record"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_identity_registration_snapshots_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["identity_accounts.tenant_id", "identity_accounts.account_id"],
            name=op.f("fk_identity_registration_snapshots_tenant_id_account_id_identity_accounts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "registration_snapshot_id",
            name=op.f("pk_identity_registration_snapshots"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "registration_id",
            "registration_version",
            name=op.f(
                "uq_identity_registration_snapshots_tenant_id_registration_id_registration_version"
            ),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key_digest",
            "registration_version",
            name=op.f(
                "uq_identity_registration_snapshots_tenant_id_idempotency_key_digest_registration_version"
            ),
        ),
    )
    op.create_index(
        "ix_identity_registration_snapshots_latest",
        "identity_registration_snapshots",
        ["tenant_id", "registration_id", "registration_version"],
    )
    op.create_index(
        "ix_identity_registration_snapshots_idempotency",
        "identity_registration_snapshots",
        ["tenant_id", "idempotency_key_digest", "registration_version"],
    )

    op.create_table(
        "identity_verification_challenges",
        sa.Column("challenge_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("registration_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("identifier_digest", sa.String(length=64), nullable=False),
        sa.Column("delivery_hint", sa.String(length=320), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "state", sa.String(length=16), server_default=sa.text("'PENDING'"), nullable=False
        ),
        sa.Column("attempt_count", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.SmallInteger(), nullable=False),
        sa.Column("send_count", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "channel IN ('EMAIL', 'PHONE')",
            name=op.f("ck_identity_verification_challenges_channel"),
        ),
        sa.CheckConstraint(
            "purpose IN ('REGISTER', 'CHANGE_EMAIL', 'CHANGE_PHONE', 'RECOVERY')",
            name=op.f("ck_identity_verification_challenges_purpose"),
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'VERIFIED', 'CONSUMED', 'EXPIRED', 'LOCKED')",
            name=op.f("ck_identity_verification_challenges_state"),
        ),
        sa.CheckConstraint(
            "identifier_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_identity_verification_challenges_identifier_digest_format"),
        ),
        sa.CheckConstraint(
            "code_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_identity_verification_challenges_code_digest_format"),
        ),
        sa.CheckConstraint(
            "request_fingerprint_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_identity_verification_challenges_request_fingerprint_digest_format"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_identity_verification_challenges_nonnegative_attempt_count"),
        ),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 20",
            name=op.f("ck_identity_verification_challenges_max_attempts"),
        ),
        sa.CheckConstraint(
            "send_count BETWEEN 1 AND 20",
            name=op.f("ck_identity_verification_challenges_send_count"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_identity_verification_challenges_expiry_after_creation"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_identity_verification_challenges_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("challenge_id", name=op.f("pk_identity_verification_challenges")),
    )
    op.create_index(
        "ix_identity_verification_challenges_lookup",
        "identity_verification_challenges",
        ["tenant_id", "channel", "identifier_digest", "created_at"],
    )
    op.create_index(
        "ix_identity_verification_challenges_expiry",
        "identity_verification_challenges",
        ["tenant_id", "expires_at"],
    )

    op.create_table(
        "identity_verification_rate_limits",
        sa.Column("rate_limit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("dimension_kind", sa.String(length=16), nullable=False),
        sa.Column("dimension_digest", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "dimension_kind IN ('IDENTIFIER', 'IP', 'DEVICE')",
            name=op.f("ck_identity_verification_rate_limits_dimension_kind"),
        ),
        sa.CheckConstraint(
            "dimension_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_identity_verification_rate_limits_dimension_digest_format"),
        ),
        sa.CheckConstraint(
            "window_seconds BETWEEN 1 AND 86400",
            name=op.f("ck_identity_verification_rate_limits_window_seconds"),
        ),
        sa.CheckConstraint(
            "request_count >= 1",
            name=op.f("ck_identity_verification_rate_limits_positive_request_count"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_identity_verification_rate_limits_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("rate_limit_id", name=op.f("pk_identity_verification_rate_limits")),
        sa.UniqueConstraint(
            "tenant_id",
            "dimension_kind",
            "dimension_digest",
            "window_started_at",
            name=op.f(
                "uq_identity_verification_rate_limits_tenant_id_dimension_kind_dimension_digest_window_started_at"
            ),
        ),
    )
    op.create_index(
        "ix_identity_verification_rate_limits_active",
        "identity_verification_rate_limits",
        ["tenant_id", "dimension_kind", "dimension_digest", "updated_at"],
    )

    op.create_table(
        "identity_consent_records",
        sa.Column("consent_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("registration_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("policy_type", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("actor_ref", sa.String(length=256), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "consent_document",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("record_sha256", sa.String(length=64), nullable=False),
        sa.Column("immutable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "policy_type IN ('PRIVACY_POLICY', 'TERMS_OF_SERVICE')",
            name=op.f("ck_identity_consent_records_policy_type"),
        ),
        sa.CheckConstraint(
            "record_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_identity_consent_records_record_sha256_format"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(consent_document) = 'object'",
            name=op.f("ck_identity_consent_records_consent_document_object"),
        ),
        sa.CheckConstraint("immutable", name=op.f("ck_identity_consent_records_immutable_record")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_identity_consent_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["identity_accounts.tenant_id", "identity_accounts.account_id"],
            name=op.f("fk_identity_consent_records_tenant_id_account_id_identity_accounts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("consent_record_id", name=op.f("pk_identity_consent_records")),
        sa.UniqueConstraint(
            "tenant_id",
            "consent_id",
            name=op.f("uq_identity_consent_records_tenant_id_consent_id"),
        ),
    )
    op.create_index(
        "ix_identity_consent_records_account",
        "identity_consent_records",
        ["tenant_id", "account_id", "accepted_at"],
    )

    op.create_table(
        "identity_reconciliation_jobs",
        sa.Column("reconciliation_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("registration_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("keycloak_user_id", sa.String(length=256), nullable=True),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
        sa.Column(
            "state", sa.String(length=16), server_default=sa.text("'PENDING'"), nullable=False
        ),
        sa.Column("attempt_count", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.SmallInteger(), server_default=sa.text("8"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column(
            "job_document",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "operation IN ('FINALIZE_PROJECTION', 'DELETE_KEYCLOAK_USER', "
            "'UPDATE_KEYCLOAK_USER', 'SET_KEYCLOAK_STATUS')",
            name=op.f("ck_identity_reconciliation_jobs_operation"),
        ),
        sa.CheckConstraint(
            "registration_id IS NOT NULL OR account_id IS NOT NULL",
            name=op.f("ck_identity_reconciliation_jobs_target_present"),
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')",
            name=op.f("ck_identity_reconciliation_jobs_state"),
        ),
        sa.CheckConstraint(
            "(state = 'RUNNING' AND claim_token IS NOT NULL AND claimed_by IS NOT NULL) "
            "OR (state <> 'RUNNING' AND claim_token IS NULL AND claimed_by IS NULL)",
            name=op.f("ck_identity_reconciliation_jobs_claim_ownership"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_identity_reconciliation_jobs_nonnegative_attempt_count"),
        ),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 64",
            name=op.f("ck_identity_reconciliation_jobs_max_attempts"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(job_document) = 'object'",
            name=op.f("ck_identity_reconciliation_jobs_job_document_object"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_identity_reconciliation_jobs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "reconciliation_job_id", name=op.f("pk_identity_reconciliation_jobs")
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "correlation_id",
            "operation",
            name=op.f("uq_identity_reconciliation_jobs_tenant_id_correlation_id_operation"),
        ),
    )
    op.create_index(
        "ix_identity_reconciliation_jobs_due",
        "identity_reconciliation_jobs",
        ["tenant_id", "state", "next_attempt_at"],
    )
    op.create_index(
        "uq_identity_reconciliation_jobs_active_account",
        "identity_reconciliation_jobs",
        ["tenant_id", "account_id"],
        unique=True,
        postgresql_where=sa.text(
            "account_id IS NOT NULL "
            "AND operation <> 'FINALIZE_PROJECTION' "
            "AND state IN ('PENDING', 'RUNNING')"
        ),
    )

    for table_name in IDENTITY_TABLES:
        _install_tenant_policy(table_name)
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = 'liyans_identity_reconciler'
                ) THEN
                    EXECUTE 'CREATE POLICY identity_reconciliation_jobs_catalog_select '
                        || 'ON identity_reconciliation_jobs FOR SELECT '
                        || 'TO liyans_identity_reconciler USING (true)';
                END IF;
            END
            $$
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION reject_identity_append_only_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION USING
                    ERRCODE = '55000',
                    MESSAGE = TG_TABLE_NAME || ' is append-only';
            END
            $$
            """
        )
    )
    for table_name in IDENTITY_APPEND_ONLY_TABLES:
        _install_append_only_trigger(table_name)
    _grant_runtime_privileges()


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP POLICY IF EXISTS identity_reconciliation_jobs_catalog_select "
            "ON identity_reconciliation_jobs"
        )
    )
    for table_name in IDENTITY_APPEND_ONLY_TABLES:
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only ON {table_name}"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS reject_identity_append_only_mutation()"))
    op.drop_index(
        "uq_identity_reconciliation_jobs_active_account",
        table_name="identity_reconciliation_jobs",
    )
    op.drop_index(
        "ix_identity_reconciliation_jobs_due",
        table_name="identity_reconciliation_jobs",
    )
    op.drop_table("identity_reconciliation_jobs")
    op.drop_index("ix_identity_consent_records_account", table_name="identity_consent_records")
    op.drop_table("identity_consent_records")
    op.drop_index(
        "ix_identity_verification_rate_limits_active",
        table_name="identity_verification_rate_limits",
    )
    op.drop_table("identity_verification_rate_limits")
    op.drop_index(
        "ix_identity_verification_challenges_expiry",
        table_name="identity_verification_challenges",
    )
    op.drop_index(
        "ix_identity_verification_challenges_lookup",
        table_name="identity_verification_challenges",
    )
    op.drop_table("identity_verification_challenges")
    op.drop_index(
        "ix_identity_registration_snapshots_idempotency",
        table_name="identity_registration_snapshots",
    )
    op.drop_index(
        "ix_identity_registration_snapshots_latest",
        table_name="identity_registration_snapshots",
    )
    op.drop_table("identity_registration_snapshots")
    op.drop_index("ix_identity_accounts_tenant_status", table_name="identity_accounts")
    op.drop_table("identity_accounts")
