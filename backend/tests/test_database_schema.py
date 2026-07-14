from __future__ import annotations

from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from liyans.infrastructure.database.models import TENANT_SCOPED_TABLES, Base

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = REPOSITORY_ROOT / "backend" / "alembic.ini"


def alembic_config(output: StringIO | None = None) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH), output_buffer=output)
    config.set_main_option("script_location", str(REPOSITORY_ROOT / "backend" / "migrations"))
    return config


def test_metadata_contains_exact_phase_1_1_table_families() -> None:
    assert set(Base.metadata.tables) == set(TENANT_SCOPED_TABLES)
    for table_name in TENANT_SCOPED_TABLES:
        table = Base.metadata.tables[table_name]
        assert "tenant_id" in table.columns
        assert table.primary_key.name == f"pk_{table_name}"


def test_all_constraints_and_indexes_are_stably_named() -> None:
    for table in Base.metadata.sorted_tables:
        assert all(constraint.name for constraint in table.constraints)
        assert all(index.name for index in table.indexes)


def test_alembic_has_one_linear_head() -> None:
    script = ScriptDirectory.from_config(alembic_config())
    assert script.get_heads() == ["20260714_0002"]
    assert script.get_base() == "20260714_0001"


def test_offline_upgrade_contains_security_and_integrity_controls() -> None:
    output = StringIO()
    command.upgrade(alembic_config(output), "head", sql=True)
    sql = output.getvalue()

    for table_name in TENANT_SCOPED_TABLES:
        assert f"CREATE TABLE {table_name}" in sql
        assert f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY" in sql
        assert f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY" in sql
        assert f"CREATE POLICY {table_name}_tenant_isolation" in sql
    assert "CREATE TRIGGER trg_audit_events_append_only" in sql
    assert "CREATE FUNCTION reject_audit_event_mutation" in sql
    assert "CREATE TABLE alembic_version" in sql
    assert "Liyan Platform" in sql


def test_offline_downgrade_is_complete_and_ordered() -> None:
    output = StringIO()
    command.downgrade(
        alembic_config(output),
        "20260714_0001:base",
        sql=True,
    )
    sql = output.getvalue()

    assert "DROP TRIGGER IF EXISTS trg_audit_events_append_only" in sql
    for table_name in reversed(TENANT_SCOPED_TABLES):
        assert f"DROP TABLE {table_name}" in sql
