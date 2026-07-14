"""Add least-privilege Outbox dispatch and SSE notification policies.

Revision ID: 20260715_0003
Revises: 20260714_0002
Create Date: 2026-07-15 02:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260715_0003"
down_revision: str | Sequence[str] | None = "20260714_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = 'liyans_dispatcher'
                ) THEN
                    RAISE EXCEPTION 'required role liyans_dispatcher does not exist';
                END IF;
                EXECUTE 'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public '
                    || 'FROM liyans_dispatcher';
                EXECUTE 'GRANT SELECT ON TABLE outbox_messages TO liyans_dispatcher';
                EXECUTE 'GRANT UPDATE ('
                    || 'state, attempts, available_at, claimed_by, claimed_at, '
                    || 'claim_expires_at, published_at, last_error_code, updated_at'
                    || ') ON TABLE outbox_messages TO liyans_dispatcher';
                EXECUTE 'CREATE POLICY outbox_messages_dispatcher_select '
                    || 'ON outbox_messages FOR SELECT TO liyans_dispatcher USING (true)';
                EXECUTE 'CREATE POLICY outbox_messages_dispatcher_update '
                    || 'ON outbox_messages FOR UPDATE TO liyans_dispatcher '
                    || 'USING (true) WITH CHECK (true)';
            END
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION notify_liyans_sse_event()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                PERFORM pg_notify(
                    'liyans_sse_events_v1',
                    json_build_object(
                        'tenant_id', NEW.tenant_id,
                        'sequence', NEW.sequence
                    )::text
                );
                RETURN NEW;
            END
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_sse_events_notify
            AFTER INSERT ON sse_events
            FOR EACH ROW EXECUTE FUNCTION notify_liyans_sse_event()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_sse_events_notify ON sse_events"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS notify_liyans_sse_event()"))
    op.execute(
        sa.text("DROP POLICY IF EXISTS outbox_messages_dispatcher_update ON outbox_messages")
    )
    op.execute(
        sa.text("DROP POLICY IF EXISTS outbox_messages_dispatcher_select ON outbox_messages")
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'liyans_dispatcher') THEN
                    EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE outbox_messages '
                        || 'FROM liyans_dispatcher';
                END IF;
            END
            $$
            """
        )
    )
