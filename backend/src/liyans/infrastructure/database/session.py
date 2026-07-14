from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from random import SystemRandom
from typing import TypeVar

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError

logger = logging.getLogger(__name__)
T = TypeVar("T")
SYSTEM_RANDOM = SystemRandom()
RETRYABLE_SQLSTATES = frozenset({"40001", "40P01"})


class TransactionIsolation(StrEnum):
    READ_COMMITTED = "READ COMMITTED"
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"


@dataclass(frozen=True, slots=True)
class SessionExecutionContext:
    tenant_id: str | None = None
    subject_ref: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class TransactionRetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.05
    max_delay_seconds: float = 1.0
    jitter_seconds: float = 0.05

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 8:
            raise ValueError("max_attempts must be between one and eight")
        if (
            min(
                self.base_delay_seconds,
                self.max_delay_seconds,
                self.jitter_seconds,
            )
            < 0
        ):
            raise ValueError("transaction retry delays cannot be negative")

    def delay_for(self, attempt: int) -> float:
        exponential = self.base_delay_seconds * (2 ** max(0, attempt - 1))
        return min(self.max_delay_seconds, exponential) + SYSTEM_RANDOM.uniform(
            0.0,
            self.jitter_seconds,
        )


SessionFactory = async_sessionmaker[AsyncSession]
TransactionalOperation = Callable[[AsyncSession], Awaitable[T]]


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autobegin=False,
    )


def _sqlstate(error: BaseException) -> str | None:
    current: object | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        state = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if isinstance(state, str):
            return state
        current = getattr(current, "orig", None)
    return None


def is_retryable_transaction_error(error: BaseException) -> bool:
    return isinstance(error, DBAPIError) and _sqlstate(error) in RETRYABLE_SQLSTATES


async def apply_session_context(
    session: AsyncSession,
    context: SessionExecutionContext,
) -> None:
    values = {
        "tenant_id": context.tenant_id or "",
        "subject_ref": context.subject_ref or "",
        "trace_id": context.trace_id or "",
    }
    await session.execute(
        text(
            "SELECT "
            "set_config('app.tenant_id', :tenant_id, true), "
            "set_config('app.subject_ref', :subject_ref, true), "
            "set_config('app.trace_id', :trace_id, true)"
        ),
        values,
    )


class DatabaseSessionManager:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        session = self.session_factory()
        try:
            yield session
        finally:
            if session.in_transaction():
                await session.rollback()
            await session.close()

    @asynccontextmanager
    async def transaction(
        self,
        *,
        context: SessionExecutionContext | None = None,
        isolation: TransactionIsolation = TransactionIsolation.READ_COMMITTED,
    ) -> AsyncIterator[AsyncSession]:
        async with self.session() as session, session.begin():
            await session.execute(text(f"SET TRANSACTION ISOLATION LEVEL {isolation.value}"))
            if context is not None:
                await apply_session_context(session, context)
            yield session

    @asynccontextmanager
    async def nested_transaction(self, session: AsyncSession) -> AsyncIterator[AsyncSession]:
        if not session.in_transaction():
            raise LiyanError(
                ErrorCode.DATABASE_TRANSACTION_STATE,
                "A nested transaction requires an active outer transaction.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )
        async with session.begin_nested():
            yield session

    async def run_transaction(
        self,
        operation: TransactionalOperation[T],
        *,
        context: SessionExecutionContext | None = None,
        isolation: TransactionIsolation = TransactionIsolation.READ_COMMITTED,
        retry_policy: TransactionRetryPolicy | None = None,
    ) -> T:
        policy = retry_policy or TransactionRetryPolicy(max_attempts=1)
        for attempt in range(1, policy.max_attempts + 1):
            try:
                async with self.transaction(context=context, isolation=isolation) as session:
                    return await operation(session)
            except DBAPIError as exc:
                if not is_retryable_transaction_error(exc) or attempt >= policy.max_attempts:
                    raise
                delay = policy.delay_for(attempt)
                logger.warning(
                    "Retrying transaction after SQLSTATE %s attempt=%s delay=%.3f",
                    _sqlstate(exc),
                    attempt,
                    delay,
                )
                await asyncio.sleep(delay)
        raise LiyanError(
            ErrorCode.DATABASE_SERIALIZATION_FAILURE,
            "The database transaction retry budget was exhausted.",
            category=ErrorCategory.DATABASE,
            retriable=True,
            status_code=503,
        )

    async def close(self) -> None:
        await self.engine.dispose()
