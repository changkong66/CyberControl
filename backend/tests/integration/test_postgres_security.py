from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from liyans.core.tenant import tenant_scope
from liyans.infrastructure.database import (
    SessionExecutionContext,
    session_context_from_tenant,
)
from liyans.infrastructure.database.models import ArtifactModel, AuditEventModel, TenantModel
from liyans.infrastructure.observability.audit import AuditDraft
from liyans.infrastructure.observability.postgres_audit import PostgresAuditStore
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


def sqlstate(error: BaseException) -> str | None:
    current: object | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        state = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if isinstance(state, str):
            return state
        current = getattr(current, "orig", None)
    return None


async def provision_tenant(migrator, tenant_id: str, trace_id: str) -> None:
    async with migrator.transaction(
        context=SessionExecutionContext(
            tenant_id=tenant_id,
            subject_ref="system:integration-provisioner",
            trace_id=trace_id,
        )
    ) as session:
        await session.execute(
            text(
                "INSERT INTO tenants "
                "(tenant_id, slug, display_name, oidc_issuer, oidc_tenant_claim) "
                "VALUES (:tenant_id, :slug, :name, :issuer, :claim)"
            ),
            {
                "tenant_id": tenant_id,
                "slug": tenant_id,
                "name": "Isolation Tenant",
                "issuer": "https://issuer.test",
                "claim": tenant_id,
            },
        )


@pytest.mark.asyncio
async def test_rls_denies_cross_tenant_reads_writes_and_context_leakage(
    postgres_runtime,
) -> None:
    database, migrator, context_a = postgres_runtime
    context_b = replace(context_a, tenant_id=f"it-{uuid4().hex[:24]}")
    await provision_tenant(migrator, context_b.tenant_id, context_b.trace_id)
    artifact_id = uuid4()

    async with database.transaction(context=session_context_from_tenant(context_a)) as session:
        session.add(
            ArtifactModel(
                artifact_id=artifact_id,
                tenant_id=context_a.tenant_id,
                schema_version="artifact.v1",
                artifact_version=1,
                resource_type="Lecturer_Doc",
                status="STAGED",
                storage_namespace="integration-artifacts",
                object_key=f"{context_a.tenant_id}/isolated",
                media_type="text/markdown",
                content_encoding="identity",
                byte_size=4,
                sha256="a" * 64,
                provenance={},
                created_by_subject=context_a.subject_ref,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )

    async with database.transaction() as session:
        rows_without_context = await session.scalar(select(func.count()).select_from(TenantModel))
    assert rows_without_context == 0

    async with database.transaction(context=session_context_from_tenant(context_b)) as session:
        foreign_artifact = await session.scalar(
            select(ArtifactModel.artifact_id).where(ArtifactModel.artifact_id == artifact_id)
        )
        foreign_tenant = await session.scalar(
            select(TenantModel.tenant_id).where(TenantModel.tenant_id == context_a.tenant_id)
        )
    assert foreign_artifact is None
    assert foreign_tenant is None

    with pytest.raises(DBAPIError) as denied:
        async with database.transaction(context=session_context_from_tenant(context_b)) as session:
            session.add(
                ArtifactModel(
                    artifact_id=uuid4(),
                    tenant_id=context_a.tenant_id,
                    schema_version="artifact.v1",
                    artifact_version=1,
                    resource_type="Lecturer_Doc",
                    status="STAGED",
                    storage_namespace="integration-artifacts",
                    object_key=f"{context_a.tenant_id}/forged",
                    media_type="text/markdown",
                    content_encoding="identity",
                    byte_size=4,
                    sha256="b" * 64,
                    provenance={},
                    created_by_subject=context_b.subject_ref,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
    assert sqlstate(denied.value) == "42501"


@pytest.mark.asyncio
async def test_audit_rows_reject_runtime_and_owner_mutation(postgres_runtime) -> None:
    database, migrator, context = postgres_runtime
    store = PostgresAuditStore(database)
    with tenant_scope(context):
        record = await store.append(
            AuditDraft(
                tenant_id=context.tenant_id,
                category="SECURITY",
                action="IMMUTABILITY_TEST",
                outcome="SUCCEEDED",
                actor_ref=context.subject_ref,
                target_ref=None,
                trace_id=context.trace_id,
                envelope_id=None,
                metadata={},
                occurred_at=datetime.now(UTC),
            )
        )

    with pytest.raises(DBAPIError) as runtime_denied:
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            await session.execute(
                update(AuditEventModel)
                .where(AuditEventModel.event_id == record.event_id)
                .values(outcome="ALTERED")
            )
    assert sqlstate(runtime_denied.value) == "42501"

    with pytest.raises(DBAPIError) as trigger_denied:
        async with migrator.transaction(context=session_context_from_tenant(context)) as session:
            await session.execute(
                update(AuditEventModel)
                .where(AuditEventModel.event_id == record.event_id)
                .values(outcome="ALTERED")
            )
    assert sqlstate(trigger_denied.value) == "55000"
