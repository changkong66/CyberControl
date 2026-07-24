from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as SQLAlchemyPoolTimeoutError

from liyans.core.errors import ErrorCode, LiyanError
from liyans.core.settings import Settings
from liyans.infrastructure.database.engine import create_database_engine
from liyans.infrastructure.database.session import (
    DatabaseSessionManager,
    TransactionRetryPolicy,
    is_retryable_transaction_error,
)


class FakeTransaction(AbstractAsyncContextManager[None]):
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> None:
        self._session.active = True

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc, traceback
        self._session.active = False
        if exc_type is None:
            self._session.commits += 1
        else:
            self._session.rollbacks += 1


class FakeSession:
    def __init__(self) -> None:
        self.active = False
        self.closed = False
        self.commits = 0
        self.rollbacks = 0
        self.nested_calls = 0
        self.execute = AsyncMock()

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)

    def begin_nested(self) -> FakeTransaction:
        self.nested_calls += 1
        return FakeTransaction(self)

    def in_transaction(self) -> bool:
        return self.active

    async def rollback(self) -> None:
        self.active = False
        self.rollbacks += 1

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakeFactory:
    session: FakeSession

    def __call__(self) -> FakeSession:
        return self.session


class FakeEngine:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


@dataclass
class SequencedFakeFactory:
    sessions: list[FakeSession]
    calls: int = 0

    def __call__(self) -> FakeSession:
        session = self.sessions[self.calls]
        self.calls += 1
        return session


class SqlStateError(Exception):
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate


def database_error(sqlstate: str) -> DBAPIError:
    return DBAPIError("statement", {}, SqlStateError(sqlstate), False)


@dataclass
class PoolMetrics:
    timeouts: list[str]

    def observe_database_pool_acquisition_timeout(self, pool_name: str) -> None:
        self.timeouts.append(pool_name)


@pytest.mark.asyncio
async def test_transaction_commits_and_closes_session() -> None:
    session = FakeSession()
    manager = DatabaseSessionManager.__new__(DatabaseSessionManager)
    manager.engine = FakeEngine(session)
    manager.session_factory = FakeFactory(session)

    async with manager.transaction() as yielded:
        assert yielded is session
        assert session.active is True

    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True


@pytest.mark.asyncio
async def test_transaction_rolls_back_on_exception() -> None:
    session = FakeSession()
    manager = DatabaseSessionManager.__new__(DatabaseSessionManager)
    manager.engine = FakeEngine(session)
    manager.session_factory = FakeFactory(session)

    with pytest.raises(RuntimeError, match="injected"):
        async with manager.transaction():
            raise RuntimeError("injected")

    assert session.rollbacks == 1
    assert session.closed is True


@pytest.mark.asyncio
async def test_pool_acquisition_timeout_is_observed_without_changing_exception() -> None:
    session = FakeSession()
    session.execute.side_effect = SQLAlchemyPoolTimeoutError("pool exhausted")
    metrics = PoolMetrics([])
    manager = DatabaseSessionManager.__new__(DatabaseSessionManager)
    manager.engine = FakeEngine(session)
    manager.session_factory = FakeFactory(session)
    manager._metrics = metrics
    manager._pool_name = "api"

    with pytest.raises(SQLAlchemyPoolTimeoutError, match="pool exhausted"):
        async with manager.transaction():
            pass

    assert metrics.timeouts == ["api"]
    assert session.rollbacks == 1
    assert session.closed is True


@pytest.mark.asyncio
async def test_nested_transaction_requires_outer_transaction() -> None:
    session = FakeSession()
    manager = DatabaseSessionManager.__new__(DatabaseSessionManager)
    with pytest.raises(LiyanError) as raised:
        async with manager.nested_transaction(session):
            pass
    assert raised.value.code == ErrorCode.DATABASE_TRANSACTION_STATE


def test_retryable_sqlstate_classification() -> None:
    assert is_retryable_transaction_error(database_error("40001"))
    assert is_retryable_transaction_error(database_error("40P01"))
    assert not is_retryable_transaction_error(database_error("23505"))


def test_engine_rejects_non_postgresql_driver() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///test.db")
    with pytest.raises(LiyanError) as raised:
        create_database_engine(settings)
    assert raised.value.code == ErrorCode.CONFIG_INVALID


def test_retry_policy_rejects_invalid_attempt_count() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        TransactionRetryPolicy(max_attempts=0)


@pytest.mark.asyncio
async def test_retry_uses_a_fresh_session_and_transaction() -> None:
    sessions = [FakeSession(), FakeSession()]
    factory = SequencedFakeFactory(sessions)
    manager = DatabaseSessionManager.__new__(DatabaseSessionManager)
    manager.engine = FakeEngine(sessions[0])
    manager.session_factory = factory
    attempts = 0

    async def operation(_session) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise database_error("40001")
        return "committed"

    result = await manager.run_transaction(
        operation,
        retry_policy=TransactionRetryPolicy(
            max_attempts=2,
            base_delay_seconds=0,
            max_delay_seconds=0,
            jitter_seconds=0,
        ),
    )

    assert result == "committed"
    assert factory.calls == 2
    assert sessions[0].rollbacks == 1
    assert sessions[1].commits == 1
    assert all(session.closed for session in sessions)
