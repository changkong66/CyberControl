from __future__ import annotations

import asyncio

import pytest

from liyans.infrastructure.persistence.postgres_outbox import (
    OUTBOX_WAKE_CHANNEL,
    OUTBOX_WAKE_PAYLOAD,
)
from liyans.infrastructure.persistence.postgres_outbox_notifications import (
    PostgresOutboxWakeListener,
)


class _Connection:
    def __init__(self) -> None:
        self.listener = None
        self.closed = False
        self.remove_started = asyncio.Event()
        self.allow_remove = asyncio.Event()

    async def add_listener(self, channel, listener) -> None:
        assert channel == OUTBOX_WAKE_CHANNEL
        self.listener = listener

    async def remove_listener(self, channel, listener) -> None:
        assert channel == OUTBOX_WAKE_CHANNEL
        assert listener == self.listener
        self.remove_started.set()
        await self.allow_remove.wait()
        self.listener = None

    async def close(self, **kwargs) -> None:
        assert kwargs == {"timeout": 2}
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed


@pytest.mark.asyncio
async def test_outbox_wake_listener_accepts_only_static_committed_hint() -> None:
    connection = _Connection()
    connection.allow_remove.set()
    wakes = 0

    def wake() -> None:
        nonlocal wakes
        wakes += 1

    async def connect(_dsn: str) -> _Connection:
        return connection

    listener = PostgresOutboxWakeListener(
        "postgresql+asyncpg://user:password@localhost/database",
        wake,
        connect_factory=connect,  # type: ignore[arg-type]
        startup_timeout_seconds=1,
    )
    await listener.start()
    assert wakes == 1
    assert connection.listener is not None

    connection.listener(None, 1, OUTBOX_WAKE_CHANNEL, OUTBOX_WAKE_PAYLOAD)
    connection.listener(None, 1, OUTBOX_WAKE_CHANNEL, "tenant-a")
    connection.listener(None, 1, "unexpected", OUTBOX_WAKE_PAYLOAD)

    assert wakes == 2
    await listener.close()
    assert connection.listener is None
    assert connection.closed is True


@pytest.mark.asyncio
async def test_outbox_wake_listener_finishes_connection_cleanup_when_cancelled() -> None:
    connection = _Connection()

    async def connect(_dsn: str) -> _Connection:
        return connection

    listener = PostgresOutboxWakeListener(
        "postgresql+asyncpg://user:password@localhost/database",
        lambda: None,
        connect_factory=connect,  # type: ignore[arg-type]
        startup_timeout_seconds=1,
    )
    await listener.start()
    close_task = asyncio.create_task(listener.close())
    await connection.remove_started.wait()
    close_task.cancel()
    await asyncio.sleep(0)
    assert close_task.done() is False

    connection.allow_remove.set()
    with pytest.raises(asyncio.CancelledError):
        await close_task

    assert connection.listener is None
    assert connection.closed is True
    assert listener.running is False


@pytest.mark.asyncio
async def test_outbox_wake_listener_starts_degraded_and_reconnects() -> None:
    first_attempt = asyncio.Event()
    connection = _Connection()
    connection.allow_remove.set()
    attempts = 0
    woke = asyncio.Event()

    async def connect(_dsn: str) -> _Connection:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            first_attempt.set()
            raise ConnectionError("injected listener outage")
        return connection

    listener = PostgresOutboxWakeListener(
        "postgresql+asyncpg://user:password@localhost/database",
        woke.set,
        reconnect_base_seconds=0.001,
        reconnect_max_seconds=0.01,
        connect_factory=connect,  # type: ignore[arg-type]
        startup_timeout_seconds=1,
    )
    await listener.start(wait_for_ready=False)
    await first_attempt.wait()
    await asyncio.wait_for(woke.wait(), timeout=1)

    assert attempts >= 2
    assert listener.connected is True
    await listener.close()


def test_outbox_wake_listener_validates_listener_boundaries() -> None:
    with pytest.raises(ValueError, match="timing"):
        PostgresOutboxWakeListener(
            "postgresql+asyncpg://user:password@localhost/database",
            lambda: None,
            reconnect_base_seconds=0,
        )
    with pytest.raises(ValueError, match="base"):
        PostgresOutboxWakeListener(
            "postgresql+asyncpg://user:password@localhost/database",
            lambda: None,
            reconnect_base_seconds=2,
            reconnect_max_seconds=1,
        )
    with pytest.raises(ValueError, match=r"postgresql\+asyncpg"):
        PostgresOutboxWakeListener("sqlite:///database", lambda: None)
