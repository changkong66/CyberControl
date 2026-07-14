"""Create Phase 1.1 tenant persistence foundation.

Revision ID: 20260714_0001
Revises:
Create Date: 2026-07-14 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260714_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = (
    "tenants",
    "artifacts",
    "idempotency_records",
    "outbox_messages",
    "audit_events",
    "sse_events",
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


def _grant_runtime_privileges() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'liyans_app') THEN
                    EXECUTE 'GRANT USAGE ON SCHEMA public TO liyans_app';
                    EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE alembic_version FROM liyans_app';
                    EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE tenants, artifacts, '
                        || 'idempotency_records, outbox_messages, audit_events, '
                        || 'sse_events FROM liyans_app';
                    EXECUTE 'GRANT SELECT ON TABLE tenants TO liyans_app';
                    EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE artifacts TO liyans_app';
                    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE '
                        || 'ON TABLE idempotency_records TO liyans_app';
                    EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE outbox_messages TO liyans_app';
                    EXECUTE 'GRANT SELECT, INSERT ON TABLE audit_events TO liyans_app';
                    EXECUTE 'GRANT SELECT, INSERT, DELETE ON TABLE sse_events TO liyans_app';
                END IF;
            END
            $$
            """
        )
    )


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "status", sa.String(length=24), server_default=sa.text("'ACTIVE'"), nullable=False
        ),
        sa.Column("oidc_issuer", sa.String(length=512), nullable=True),
        sa.Column("oidc_tenant_claim", sa.String(length=256), nullable=True),
        sa.Column(
            "settings_document",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'DEPROVISIONED')",
            name=op.f("ck_tenants_status"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_tenants_positive_version")),
        sa.CheckConstraint(
            "(oidc_issuer IS NULL) = (oidc_tenant_claim IS NULL)",
            name=op.f("ck_tenants_oidc_binding_pair"),
        ),
        sa.CheckConstraint(
            "slug = lower(slug) AND slug ~ '^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$'",
            name=op.f("ck_tenants_canonical_slug"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )
    op.create_table(
        "artifacts",
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("artifact_version", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=24), server_default=sa.text("'STAGED'"), nullable=False
        ),
        sa.Column("storage_namespace", sa.String(length=128), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column(
            "content_encoding",
            sa.String(length=32),
            server_default=sa.text("'identity'"),
            nullable=False,
        ),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("source_envelope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("blueprint_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("blueprint_version", sa.String(length=64), nullable=True),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_version", sa.Integer(), nullable=True),
        sa.Column("block_id", sa.String(length=128), nullable=True),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by_subject", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('STAGED', 'VERIFIED', 'PUBLISHED', 'REJECTED', 'SUPERSEDED', 'DELETED')",
            name=op.f("ck_artifacts_status"),
        ),
        sa.CheckConstraint(
            "resource_type IN ('Lecturer_Doc', 'MindMap', 'Gradient_Quiz', "
            "'Simulation_Code', 'Extension_Material')",
            name=op.f("ck_artifacts_resource_type"),
        ),
        sa.CheckConstraint("artifact_version >= 1", name=op.f("ck_artifacts_positive_version")),
        sa.CheckConstraint("byte_size >= 1", name=op.f("ck_artifacts_positive_byte_size")),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_artifacts_sha256_format")),
        sa.CheckConstraint(
            "(candidate_id IS NULL) = (candidate_version IS NULL)",
            name=op.f("ck_artifacts_candidate_version_pair"),
        ),
        sa.CheckConstraint(
            "candidate_version IS NULL OR candidate_version >= 1",
            name=op.f("ck_artifacts_candidate_version_positive"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(provenance) = 'object'",
            name=op.f("ck_artifacts_provenance_object"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_artifacts_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("artifact_id", name=op.f("pk_artifacts")),
        sa.UniqueConstraint(
            "tenant_id",
            "storage_namespace",
            "object_key",
            name=op.f("uq_artifacts_tenant_id_storage_namespace_object_key"),
        ),
    )
    op.create_index(
        "ix_artifacts_tenant_resource_created",
        "artifacts",
        ["tenant_id", "resource_type", "created_at"],
    )
    op.create_index(
        "ix_artifacts_tenant_candidate_version",
        "artifacts",
        ["tenant_id", "candidate_id", "candidate_version"],
    )
    op.create_table(
        "idempotency_records",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "state", sa.String(length=24), server_default=sa.text("'BUFFERED'"), nullable=False
        ),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_status_code", sa.SmallInteger(), nullable=True),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "state IN ('BUFFERED', 'PROCESSING', 'COMPLETED')",
            name=op.f("ck_idempotency_records_state"),
        ),
        sa.CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_idempotency_records_request_digest_format"),
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name=op.f("ck_idempotency_records_lease_pair"),
        ),
        sa.CheckConstraint(
            "response_status_code IS NULL OR response_status_code BETWEEN 100 AND 599",
            name=op.f("ck_idempotency_records_response_status_code"),
        ),
        sa.CheckConstraint(
            "result_payload IS NULL OR jsonb_typeof(result_payload) = 'object'",
            name=op.f("ck_idempotency_records_result_payload_object"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_idempotency_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "idempotency_key",
            name=op.f("pk_idempotency_records"),
        ),
    )
    op.create_index(
        "ix_idempotency_records_expires_at",
        "idempotency_records",
        ["expires_at"],
    )
    op.create_table(
        "outbox_messages",
        sa.Column("outbox_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("envelope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("message_kind", sa.String(length=16), nullable=False),
        sa.Column("partition_key", sa.String(length=256), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=128), nullable=True),
        sa.Column("aggregate_id", sa.String(length=256), nullable=True),
        sa.Column("aggregate_version", sa.BigInteger(), nullable=True),
        sa.Column("envelope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("envelope_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "state", sa.String(length=24), server_default=sa.text("'PENDING'"), nullable=False
        ),
        sa.Column(
            "priority", sa.String(length=16), server_default=sa.text("'NORMAL'"), nullable=False
        ),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.SmallInteger(), server_default=sa.text("3"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'CLAIMED', 'PUBLISHED', 'DEAD')",
            name=op.f("ck_outbox_messages_state"),
        ),
        sa.CheckConstraint("sequence >= 0", name=op.f("ck_outbox_messages_nonnegative_sequence")),
        sa.CheckConstraint(
            "attempts >= 0 AND attempts <= max_attempts",
            name=op.f("ck_outbox_messages_attempt_budget"),
        ),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 16",
            name=op.f("ck_outbox_messages_max_attempts"),
        ),
        sa.CheckConstraint(
            "envelope_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_outbox_messages_envelope_sha256_format"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(envelope) = 'object'",
            name=op.f("ck_outbox_messages_envelope_object"),
        ),
        sa.CheckConstraint(
            "(claimed_by IS NULL AND claimed_at IS NULL AND claim_expires_at IS NULL) OR "
            "(claimed_by IS NOT NULL AND claimed_at IS NOT NULL AND claim_expires_at IS NOT NULL)",
            name=op.f("ck_outbox_messages_claim_fields"),
        ),
        sa.CheckConstraint(
            "state <> 'PUBLISHED' OR published_at IS NOT NULL",
            name=op.f("ck_outbox_messages_published_timestamp"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_outbox_messages_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("outbox_id", name=op.f("pk_outbox_messages")),
        sa.UniqueConstraint(
            "tenant_id",
            "envelope_id",
            name=op.f("uq_outbox_messages_tenant_id_envelope_id"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "partition_key",
            "sequence",
            name=op.f("uq_outbox_messages_tenant_id_partition_key_sequence"),
        ),
    )
    op.create_index(
        "ix_outbox_messages_dispatch",
        "outbox_messages",
        ["state", "available_at", "created_at"],
        postgresql_where=sa.text("state IN ('PENDING', 'CLAIMED')"),
    )
    op.create_index(
        "ix_outbox_messages_tenant_created",
        "outbox_messages",
        ["tenant_id", "created_at"],
    )
    op.create_table(
        "audit_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("outcome", sa.String(length=64), nullable=False),
        sa.Column("actor_ref", sa.String(length=256), nullable=False),
        sa.Column("target_ref", sa.String(length=512), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("envelope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "hash_algorithm",
            sa.String(length=16),
            server_default=sa.text("'SHA-256'"),
            nullable=False,
        ),
        sa.Column("signing_key_version", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("sequence >= 0", name=op.f("ck_audit_events_nonnegative_sequence")),
        sa.CheckConstraint(
            "previous_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_audit_events_previous_hash_format"),
        ),
        sa.CheckConstraint(
            "event_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_audit_events_event_hash_format"),
        ),
        sa.CheckConstraint(
            "hash_algorithm = 'SHA-256'", name=op.f("ck_audit_events_hash_algorithm")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name=op.f("ck_audit_events_metadata_object"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_audit_events_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_audit_events")),
        sa.UniqueConstraint(
            "tenant_id", "sequence", name=op.f("uq_audit_events_tenant_id_sequence")
        ),
        sa.UniqueConstraint(
            "tenant_id", "event_hash", name=op.f("uq_audit_events_tenant_id_event_hash")
        ),
    )
    op.create_index(
        "ix_audit_events_tenant_occurred",
        "audit_events",
        ["tenant_id", "occurred_at"],
    )
    op.create_index("ix_audit_events_trace_id", "audit_events", ["trace_id"])
    op.create_table(
        "sse_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("stream_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("envelope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("data_sha256", sa.String(length=64), nullable=False),
        sa.Column("emitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("sequence >= 0", name=op.f("ck_sse_events_nonnegative_sequence")),
        sa.CheckConstraint(
            "data_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_sse_events_data_sha256_format"),
        ),
        sa.CheckConstraint("jsonb_typeof(data) = 'object'", name=op.f("ck_sse_events_data_object")),
        sa.CheckConstraint("expires_at > emitted_at", name=op.f("ck_sse_events_retention_window")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_sse_events_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_sse_events")),
        sa.UniqueConstraint("tenant_id", "sequence", name=op.f("uq_sse_events_tenant_id_sequence")),
    )
    op.create_index(
        "ix_sse_events_tenant_emitted",
        "sse_events",
        ["tenant_id", "emitted_at"],
    )
    op.create_index(
        "ix_sse_events_tenant_stream_sequence",
        "sse_events",
        ["tenant_id", "stream_id", "sequence"],
    )
    op.create_index("ix_sse_events_expires_at", "sse_events", ["expires_at"])

    for table_name in TENANT_SCOPED_TABLES:
        _install_tenant_policy(table_name)

    op.execute(
        sa.text(
            """
            CREATE FUNCTION reject_audit_event_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION USING
                    ERRCODE = '55000',
                    MESSAGE = 'audit_events is append-only';
            END
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()
            """
        )
    )
    _grant_runtime_privileges()


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS reject_audit_event_mutation()"))
    op.drop_table("sse_events")
    op.drop_table("audit_events")
    op.drop_table("outbox_messages")
    op.drop_table("idempotency_records")
    op.drop_table("artifacts")
    op.drop_table("tenants")
