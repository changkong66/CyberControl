from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from liyans.core.settings import Settings
from liyans.core.tenant import TenantContext
from liyans.infrastructure.database import (
    DatabaseSessionManager,
    SessionExecutionContext,
    create_database_engine,
)

RUNTIME_URL = os.getenv("LIYAN_TEST_DATABASE_URL")
MIGRATION_URL = os.getenv("LIYAN_TEST_MIGRATION_DATABASE_URL")
DISPATCHER_URL = os.getenv("LIYAN_TEST_DISPATCHER_DATABASE_URL")
RECONCILER_URL = os.getenv("LIYAN_TEST_RECONCILER_DATABASE_URL")


async def assert_restricted_role(
    database: DatabaseSessionManager,
    *,
    label: str,
) -> None:
    async with database.transaction() as session:
        result = await session.execute(
            text(
                "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
        )
        role_name, is_superuser, bypasses_rls = result.one()
    if is_superuser or bypasses_rls:
        pytest.fail(f"{label} role {role_name} must not be superuser or BYPASSRLS")


@pytest.fixture
async def postgres_runtime():
    if not RUNTIME_URL or not MIGRATION_URL:
        pytest.skip("PostgreSQL integration URLs are not configured")
    integration_settings = {
        "database_pool_timeout_seconds": 60,
    }
    runtime = DatabaseSessionManager(
        create_database_engine(Settings(database_url=RUNTIME_URL, **integration_settings))
    )
    migrator = DatabaseSessionManager(
        create_database_engine(Settings(database_url=MIGRATION_URL, **integration_settings))
    )
    tenant_id = f"it-{uuid4().hex[:24]}"
    context = TenantContext(
        tenant_id=tenant_id,
        subject_ref="subject:integration",
        roles=frozenset({"integration"}),
        scopes=frozenset({"test"}),
        trace_id="c" * 32,
    )
    try:
        await assert_restricted_role(runtime, label="runtime")
        await assert_restricted_role(migrator, label="migration")
        async with migrator.transaction(
            context=SessionExecutionContext(
                tenant_id=tenant_id,
                subject_ref="system:integration-provisioner",
                trace_id=context.trace_id,
            )
        ) as session:
            await session.execute(
                text(
                    "INSERT INTO tenants "
                    "(tenant_id, slug, display_name, oidc_issuer, oidc_tenant_claim) "
                    "VALUES (:tenant_id, :slug, :display_name, :issuer, :tenant_claim)"
                ),
                {
                    "tenant_id": tenant_id,
                    "slug": tenant_id,
                    "display_name": "Integration Tenant",
                    "issuer": "https://issuer.test",
                    "tenant_claim": tenant_id,
                },
            )
        yield runtime, migrator, context
    finally:
        await runtime.close()
        await migrator.close()


@pytest.fixture
async def postgres_dispatcher(postgres_runtime):
    if not DISPATCHER_URL:
        pytest.skip("PostgreSQL dispatcher integration URL is not configured")
    dispatcher = DatabaseSessionManager(
        create_database_engine(
            Settings(database_url=DISPATCHER_URL),
            application_name="liyans-integration-dispatcher",
        )
    )
    try:
        await assert_restricted_role(dispatcher, label="dispatcher")
        yield dispatcher
    finally:
        await dispatcher.close()


@pytest.fixture
async def postgres_reconciler(postgres_runtime):
    del postgres_runtime
    if not RECONCILER_URL:
        pytest.skip("PostgreSQL reconciler integration URL is not configured")
    reconciler = DatabaseSessionManager(
        create_database_engine(
            Settings(database_url=RECONCILER_URL),
            application_name="liyans-integration-identity-reconciler",
        )
    )
    try:
        await assert_restricted_role(reconciler, label="identity reconciler")
        yield reconciler
    finally:
        await reconciler.close()
