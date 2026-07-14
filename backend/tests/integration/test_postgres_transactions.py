from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from liyans.infrastructure.database import (
    TransactionIsolation,
    TransactionRetryPolicy,
    session_context_from_tenant,
)
from liyans.infrastructure.database.models import ArtifactModel
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


def artifact(tenant_id: str, object_key: str, *, version: int = 1) -> ArtifactModel:
    return ArtifactModel(
        artifact_id=uuid4(),
        tenant_id=tenant_id,
        schema_version="artifact.v1",
        artifact_version=version,
        resource_type="Lecturer_Doc",
        status="STAGED",
        storage_namespace="integration-artifacts",
        object_key=object_key,
        media_type="text/markdown",
        content_encoding="identity",
        byte_size=4,
        sha256="a" * 64,
        provenance={},
        created_by_subject="subject:integration",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_nested_transaction_rolls_back_only_the_savepoint(postgres_runtime) -> None:
    database, _migrator, context = postgres_runtime
    outer_first = artifact(context.tenant_id, f"{context.tenant_id}/outer-first")
    nested = artifact(context.tenant_id, f"{context.tenant_id}/nested")
    outer_second = artifact(context.tenant_id, f"{context.tenant_id}/outer-second")

    async with database.transaction(context=session_context_from_tenant(context)) as session:
        session.add(outer_first)
        await session.flush()
        with pytest.raises(RuntimeError, match="savepoint"):
            async with database.nested_transaction(session):
                session.add(nested)
                await session.flush()
                raise RuntimeError("savepoint")
        session.add(outer_second)

    async with database.transaction(context=session_context_from_tenant(context)) as session:
        result = await session.execute(
            select(ArtifactModel.object_key)
            .where(ArtifactModel.tenant_id == context.tenant_id)
            .order_by(ArtifactModel.object_key)
        )
        keys = list(result.scalars())

    assert keys == sorted([outer_first.object_key, outer_second.object_key])


@pytest.mark.asyncio
async def test_serializable_conflict_retries_with_a_fresh_transaction(
    postgres_runtime,
) -> None:
    database, _migrator, context = postgres_runtime
    target = artifact(context.tenant_id, f"{context.tenant_id}/serializable")
    async with database.transaction(context=session_context_from_tenant(context)) as session:
        session.add(target)

    attempts = [0, 0]
    arrivals = 0
    arrival_lock = asyncio.Lock()
    both_read = asyncio.Event()

    def operation(index: int):
        async def increment(session) -> int:
            nonlocal arrivals
            attempts[index] += 1
            version = await session.scalar(
                select(ArtifactModel.artifact_version).where(
                    ArtifactModel.artifact_id == target.artifact_id
                )
            )
            assert version is not None
            if attempts[index] == 1:
                async with arrival_lock:
                    arrivals += 1
                    if arrivals == 2:
                        both_read.set()
                await asyncio.wait_for(both_read.wait(), timeout=5)
            await session.execute(
                update(ArtifactModel)
                .where(ArtifactModel.artifact_id == target.artifact_id)
                .values(
                    artifact_version=version + 1,
                    updated_at=datetime.now(UTC),
                )
            )
            return version + 1

        return increment

    policy = TransactionRetryPolicy(
        max_attempts=3,
        base_delay_seconds=0.001,
        max_delay_seconds=0.01,
        jitter_seconds=0,
    )
    await asyncio.wait_for(
        asyncio.gather(
            database.run_transaction(
                operation(0),
                context=session_context_from_tenant(context),
                isolation=TransactionIsolation.SERIALIZABLE,
                retry_policy=policy,
            ),
            database.run_transaction(
                operation(1),
                context=session_context_from_tenant(context),
                isolation=TransactionIsolation.SERIALIZABLE,
                retry_policy=policy,
            ),
        ),
        timeout=10,
    )

    async with database.transaction(context=session_context_from_tenant(context)) as session:
        final_version = await session.scalar(
            select(ArtifactModel.artifact_version).where(
                ArtifactModel.artifact_id == target.artifact_id
            )
        )

    assert final_version == 3
    assert sum(attempts) >= 3


@pytest.mark.asyncio
async def test_pool_recovers_after_backend_connection_termination(postgres_runtime) -> None:
    database, _migrator, context = postgres_runtime
    with pytest.raises(DBAPIError):
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            await session.execute(text("SELECT pg_terminate_backend(pg_backend_pid())"))

    async with database.transaction(context=session_context_from_tenant(context)) as session:
        recovered = await session.scalar(text("SELECT 1"))

    assert recovered == 1
