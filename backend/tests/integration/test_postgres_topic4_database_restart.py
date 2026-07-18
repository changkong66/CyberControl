from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from liyans.core.settings import Settings
from liyans.core.tenant import tenant_scope
from liyans.domains.knowledge.lifecycle import KnowledgeBaseBuildCommand
from liyans.infrastructure.database import DatabaseSessionManager, create_database_engine

from .test_postgres_topic4_knowledge import (
    COURSE_ID,
    _c2_services,
    _c2_source_command,
    _seed_topic1,
)

pytestmark = pytest.mark.integration


def _restart_database_container(container_name: str) -> None:
    subprocess.run(
        ["docker", "restart", container_name],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        probe = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_name],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if probe.stdout.strip() == "healthy":
            return
        time.sleep(1)
    raise RuntimeError("PostgreSQL test container did not become healthy after restart")


@pytest.mark.asyncio
async def test_c2_database_restart_preserves_active_index_and_manifest(
    postgres_runtime,
    tmp_path: Path,
) -> None:
    if os.getenv("LIYAN_RUN_DATABASE_RESTART_TEST") != "1":
        pytest.skip("set LIYAN_RUN_DATABASE_RESTART_TEST=1 to execute the Docker restart probe")
    container_name = os.getenv("LIYAN_TEST_DATABASE_CONTAINER")
    if not container_name:
        pytest.fail("LIYAN_TEST_DATABASE_CONTAINER is required for the restart probe")
    database, _migrator, context = postgres_runtime
    artifact_root = tmp_path / "artifacts"
    with tenant_scope(context):
        _repository, _writer, _transactions, _indexes, lifecycle, _retrieval = _c2_services(
            database,
            artifact_root,
            instance_id="topic4-c2-db-restart-before",
        )
        await _seed_topic1(database)
        imported = await lifecycle.import_source(
            _c2_source_command(version="2026.8", title="Database Restart Source"),
            idempotency_key="topic4-c2-restart-source-000000000001",
        )
        built = await lifecycle.build_and_activate(
            KnowledgeBaseBuildCommand(
                course_id=COURSE_ID,
                version="kb-restart-2026.8",
                source_document_version_ids=(imported.source_version.source_document_version_id,),
            ),
            idempotency_key="topic4-c2-restart-build-000000000001",
        )
        await database.close()
        _restart_database_container(container_name)

        restarted_database = DatabaseSessionManager(
            create_database_engine(
                Settings(database_url=os.environ["LIYAN_TEST_DATABASE_URL"]),
                application_name="liyans-c2-database-restart-probe",
            )
        )
        try:
            (
                _fresh_repository,
                _fresh_writer,
                _fresh_transactions,
                _fresh_indexes,
                _fresh_lifecycle,
                fresh_retrieval,
            ) = _c2_services(
                restarted_database,
                artifact_root,
                instance_id="topic4-c2-db-restart-after",
            )
            loaded = await fresh_retrieval.load_active(COURSE_ID)
        finally:
            await restarted_database.close()

    assert (
        loaded.knowledge_base.knowledge_base_version_id
        == built.knowledge_base.knowledge_base_version_id
    )
    assert loaded.manifest.record_sha256 == built.ready_manifest.record_sha256
    assert loaded.index.entries
