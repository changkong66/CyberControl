from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as SQLAlchemyPoolTimeoutError

from liyans.core.settings import Settings
from liyans.infrastructure.database import (
    DatabaseSessionManager,
    create_database_engine,
    session_context_from_tenant,
)
from liyans.infrastructure.observability.metrics import PlatformMetrics

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_cancelled_query_returns_connection_and_allows_follow_up_query(
    postgres_runtime,
) -> None:
    database, _migrator, context = postgres_runtime
    query_started = asyncio.Event()

    async def run_blocked_query() -> None:
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            query_started.set()
            await session.execute(text("SELECT pg_sleep(30)"))

    task = asyncio.create_task(run_blocked_query())
    await query_started.wait()
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    async with database.transaction(context=session_context_from_tenant(context)) as session:
        assert await session.scalar(text("SELECT 1")) == 1
    assert database.engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_absolute_pool_metric_returns_to_zero_after_cancellation() -> None:
    runtime_url = os.getenv("LIYAN_TEST_DATABASE_URL")
    if not runtime_url:
        pytest.skip("PostgreSQL integration URL is not configured")
    metrics = PlatformMetrics()
    database = DatabaseSessionManager(
        create_database_engine(
            Settings(database_url=runtime_url, database_pool_timeout_seconds=60),
            metrics=metrics,
            pool_name="api",
        ),
        metrics=metrics,
        pool_name="api",
    )
    query_started = asyncio.Event()

    async def run_blocked_query() -> None:
        async with database.transaction() as session:
            query_started.set()
            await session.execute(text("SELECT pg_sleep(30)"))

    try:
        task = asyncio.create_task(run_blocked_query())
        await query_started.wait()
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert database.engine.pool.checkedout() == 0
        rendered = metrics.render().decode("utf-8")
        assert 'liyans_database_pool_checked_out{pool="api"} 0.0' in rendered
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_absolute_pool_metric_tracks_timeout_and_terminal_return() -> None:
    runtime_url = os.getenv("LIYAN_TEST_DATABASE_URL")
    if not runtime_url:
        pytest.skip("PostgreSQL integration URL is not configured")
    metrics = PlatformMetrics()
    database = DatabaseSessionManager(
        create_database_engine(
            Settings(
                database_url=runtime_url,
                database_pool_size=1,
                database_max_overflow=0,
                database_pool_timeout_seconds=0.1,
            ),
            metrics=metrics,
            pool_name="api",
        ),
        metrics=metrics,
        pool_name="api",
    )

    try:
        async with database.transaction() as holder:
            assert await holder.scalar(text("SELECT 1")) == 1
            with pytest.raises(SQLAlchemyPoolTimeoutError):
                async with database.transaction() as blocked:
                    await blocked.scalar(text("SELECT 1"))
            rendered = metrics.render().decode("utf-8")
            assert 'liyans_database_pool_checked_out{pool="api"} 1.0' in rendered
            assert 'liyans_database_pool_acquisition_timeouts_total{pool="api"} 1.0' in rendered

        assert database.engine.pool.checkedout() == 0
        rendered = metrics.render().decode("utf-8")
        assert 'liyans_database_pool_checked_out{pool="api"} 0.0' in rendered
    finally:
        await database.close()
