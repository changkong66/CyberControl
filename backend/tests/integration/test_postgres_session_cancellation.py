from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from liyans.infrastructure.database import session_context_from_tenant

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
