from __future__ import annotations

from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from liyans.domains.compliance.models import TOPIC4_COMPLIANCE_TABLES
from liyans.domains.knowledge.models import TOPIC4_KNOWLEDGE_TABLES
from liyans.domains.privacy.models import TOPIC4_PRIVACY_TABLES
from liyans.domains.qa.models import TOPIC4_QA_TABLES
from liyans.domains.revision.models import TOPIC4_REVISION_TABLES
from liyans.domains.security.models import TOPIC4_SECURITY_TABLES
from liyans.domains.topic1.models import TOPIC1_TENANT_TABLES
from liyans.domains.topic2.models import TOPIC2_TENANT_TABLES
from liyans.domains.topic3.models import TOPIC3_TENANT_TABLES
from liyans.domains.verification.models import TOPIC4_CONTROL_TABLES
from liyans.domains.verification.release_models import TOPIC4_RELEASE_TABLES
from liyans.infrastructure.database.models import TENANT_SCOPED_TABLES, Base

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = REPOSITORY_ROOT / "backend" / "alembic.ini"
TOPIC4_TENANT_TABLES = (
    *TOPIC4_CONTROL_TABLES,
    *TOPIC4_KNOWLEDGE_TABLES,
    *TOPIC4_REVISION_TABLES,
    *TOPIC4_SECURITY_TABLES,
    *TOPIC4_PRIVACY_TABLES,
    *TOPIC4_COMPLIANCE_TABLES,
    *TOPIC4_QA_TABLES,
    *TOPIC4_RELEASE_TABLES,
)
ALL_TENANT_TABLES = (
    *TENANT_SCOPED_TABLES,
    *TOPIC1_TENANT_TABLES,
    *TOPIC2_TENANT_TABLES,
    *TOPIC3_TENANT_TABLES,
    *TOPIC4_TENANT_TABLES,
)


def alembic_config(output: StringIO | None = None) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH), output_buffer=output)
    config.set_main_option("script_location", str(REPOSITORY_ROOT / "backend" / "migrations"))
    return config


def test_metadata_contains_all_frozen_tenant_table_families() -> None:
    assert set(Base.metadata.tables) == set(ALL_TENANT_TABLES)
    for table_name in ALL_TENANT_TABLES:
        table = Base.metadata.tables[table_name]
        assert "tenant_id" in table.columns
        assert table.primary_key.name == f"pk_{table_name}"


def test_all_constraints_and_indexes_are_stably_named() -> None:
    for table in Base.metadata.sorted_tables:
        assert all(constraint.name for constraint in table.constraints)
        assert all(index.name for index in table.indexes)


def test_alembic_has_one_linear_head() -> None:
    script = ScriptDirectory.from_config(alembic_config())
    assert script.get_heads() == ["20260716_0009"]
    assert script.get_base() == "20260714_0001"


def test_offline_upgrade_contains_security_and_integrity_controls() -> None:
    output = StringIO()
    command.upgrade(alembic_config(output), "head", sql=True)
    sql = output.getvalue()

    for table_name in ALL_TENANT_TABLES:
        assert f"CREATE TABLE {table_name}" in sql
        assert f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY" in sql
        assert f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY" in sql
        assert f"CREATE POLICY {table_name}_tenant_isolation" in sql
    assert "CREATE TRIGGER trg_audit_events_append_only" in sql
    assert "CREATE FUNCTION reject_audit_event_mutation" in sql
    assert "CREATE TRIGGER trg_topic1_graph_snapshots_append_only" in sql
    assert "CREATE FUNCTION reject_topic1_graph_snapshot_mutation" in sql
    assert "CREATE FUNCTION reject_topic2_history_mutation" in sql
    for table_name in TOPIC2_TENANT_TABLES:
        assert f"CREATE TRIGGER trg_{table_name}_append_only" in sql
    assert "CREATE FUNCTION reject_topic3_history_mutation" in sql
    for table_name in TOPIC3_TENANT_TABLES:
        assert f"CREATE TRIGGER trg_{table_name}_append_only" in sql
    assert "CREATE FUNCTION reject_topic4_history_mutation" in sql
    for table_name in TOPIC4_TENANT_TABLES:
        assert f"CREATE TRIGGER trg_{table_name}_append_only" in sql
    assert "CREATE TABLE alembic_version" in sql
    assert "Liyan Platform" in sql


def test_offline_downgrade_is_complete_and_ordered() -> None:
    output = StringIO()
    command.downgrade(
        alembic_config(output),
        "20260716_0009:base",
        sql=True,
    )
    sql = output.getvalue()

    assert "DROP TRIGGER IF EXISTS trg_audit_events_append_only" in sql
    assert "DROP TRIGGER IF EXISTS trg_topic1_graph_snapshots_append_only" in sql
    assert "DROP FUNCTION IF EXISTS reject_topic2_history_mutation" in sql
    for table_name in TOPIC2_TENANT_TABLES:
        assert f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only" in sql
    assert "DROP FUNCTION IF EXISTS reject_topic3_history_mutation" in sql
    for table_name in TOPIC3_TENANT_TABLES:
        assert f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only" in sql
    assert "DROP FUNCTION IF EXISTS reject_topic4_history_mutation" in sql
    for table_name in TOPIC4_TENANT_TABLES:
        assert f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only" in sql
    for table_name in reversed(ALL_TENANT_TABLES):
        assert f"DROP TABLE {table_name}" in sql
