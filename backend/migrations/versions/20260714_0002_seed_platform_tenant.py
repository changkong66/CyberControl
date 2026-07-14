"""Seed the infrastructure platform tenant.

Revision ID: 20260714_0002
Revises: 20260714_0001
Create Date: 2026-07-14 23:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_0002"
down_revision: str | Sequence[str] | None = "20260714_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SELECT set_config('app.tenant_id', 'platform', true)"))
    op.execute(
        sa.text(
            """
            INSERT INTO tenants (tenant_id, slug, display_name, settings_document)
            VALUES ('platform', 'platform', 'Liyan Platform', '{"system": true}'::jsonb)
            ON CONFLICT (tenant_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("SELECT set_config('app.tenant_id', 'platform', true)"))
    op.execute(sa.text("DELETE FROM tenants WHERE tenant_id = 'platform'"))
