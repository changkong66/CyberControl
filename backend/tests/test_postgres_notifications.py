from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from liyans.infrastructure.streaming import (
    InMemorySSEReplayLog,
    PostgresSSENotificationBridge,
    SSEBroker,
)
from liyans.infrastructure.streaming.postgres_notifications import (
    SSE_NOTIFICATION_CHANNEL,
    SSENotification,
)


class _Connection:
    def __init__(self, *, block_remove: bool = False) -> None:
        self.closed = False
        self.listener: Callable[..., Any] | None = None
        self.remove_started = asyncio.Event()
        self.allow_remove = asyncio.Event()
        if not block_remove:
            self.allow_remove.set()

    async def add_listener(self, _channel: str, callback: Callable[..., Any]) -> None:
        self.listener = callback

    async def remove_listener(self, _channel: str, callback: Callable[..., Any]) -> None:
        self.remove_started.set()
        assert callback == self.listener
        await self.allow_remove.wait()
        self.listener = None

    async def close(self, *, timeout: float) -> None:  # noqa: ASYNC109 - asyncpg API parity.
        assert timeout == 2
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed


@pytest.mark.asyncio
async def test_notification_bridge_closes_listener_and_connection_gracefully() -> None:
    connection = _Connection()

    async def connect(_dsn: str) -> _Connection:
        return connection

    bridge = PostgresSSENotificationBridge(
        "postgresql+asyncpg://user:password@localhost/database",
        SSEBroker(InMemorySSEReplayLog()),
        connect_factory=connect,  # type: ignore[arg-type]
        startup_timeout_seconds=1,
    )
    await bridge.start()

    await bridge.close()

    assert connection.listener is None
    assert connection.closed is True
    assert bridge.running is False


@pytest.mark.asyncio
async def test_notification_bridge_finishes_connection_cleanup_when_close_is_cancelled() -> None:
    connection = _Connection(block_remove=True)

    async def connect(_dsn: str) -> _Connection:
        return connection

    bridge = PostgresSSENotificationBridge(
        "postgresql+asyncpg://user:password@localhost/database",
        SSEBroker(InMemorySSEReplayLog()),
        connect_factory=connect,  # type: ignore[arg-type]
        startup_timeout_seconds=1,
    )
    await bridge.start()
    close_task = asyncio.create_task(bridge.close())
    await connection.remove_started.wait()

    close_task.cancel()
    await asyncio.sleep(0)
    assert close_task.done() is False
    assert connection.closed is False

    connection.allow_remove.set()
    with pytest.raises(asyncio.CancelledError):
        await close_task

    assert connection.listener is None
    assert connection.closed is True
    assert bridge.running is False


@pytest.mark.asyncio
async def test_notification_bridge_start_timeout_closes_late_connection() -> None:
    connection = _Connection()

    async def connect(_dsn: str) -> _Connection:
        await asyncio.sleep(0.02)
        return connection

    bridge = PostgresSSENotificationBridge(
        "postgresql+asyncpg://user:password@localhost/database",
        SSEBroker(InMemorySSEReplayLog()),
        connect_factory=connect,  # type: ignore[arg-type]
        startup_timeout_seconds=0.005,
    )

    with pytest.raises(RuntimeError, match="did not become ready"):
        await bridge.start()

    assert connection.closed is True
    assert bridge.running is False


def test_notification_bridge_validates_configuration_and_unstarted_lifecycle() -> None:
    broker = SSEBroker(InMemorySSEReplayLog())
    with pytest.raises(ValueError, match="queue_size"):
        PostgresSSENotificationBridge(
            "postgresql+asyncpg://user:password@localhost/database",
            broker,
            queue_size=0,
        )
    with pytest.raises(ValueError, match="timing"):
        PostgresSSENotificationBridge(
            "postgresql+asyncpg://user:password@localhost/database",
            broker,
            reconnect_base_seconds=0,
        )
    with pytest.raises(ValueError, match="base"):
        PostgresSSENotificationBridge(
            "postgresql+asyncpg://user:password@localhost/database",
            broker,
            reconnect_base_seconds=2,
            reconnect_max_seconds=1,
        )
    with pytest.raises(ValueError, match=r"postgresql\+asyncpg"):
        PostgresSSENotificationBridge("sqlite:///database", broker)


@pytest.mark.asyncio
async def test_notification_bridge_unstarted_close_and_duplicate_start_are_idempotent() -> None:
    connection = _Connection()

    async def connect(_dsn: str) -> _Connection:
        return connection

    bridge = PostgresSSENotificationBridge(
        "postgresql+asyncpg://user:password@localhost/database",
        SSEBroker(InMemorySSEReplayLog()),
        connect_factory=connect,  # type: ignore[arg-type]
        startup_timeout_seconds=1,
    )
    assert bridge.connected is False
    assert bridge.last_error is None
    await bridge.close()
    await bridge.start()
    await bridge.start()
    await bridge.close()
    assert connection.closed is True


def test_notification_bridge_rejects_invalid_payloads_and_records_overflow() -> None:
    class Metrics:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int]] = []

        def observe_sse(self, operation: str, outcome: str, count: int = 1) -> None:
            self.calls.append((operation, outcome, count))

    metrics = Metrics()
    bridge = PostgresSSENotificationBridge(
        "postgresql+asyncpg://user:password@localhost/database",
        SSEBroker(InMemorySSEReplayLog()),
        queue_size=1,
        metrics=metrics,
    )
    valid = '{"tenant_id":"tenant-a","sequence":1}'

    bridge._on_notification(None, 1, "wrong-channel", valid)  # type: ignore[arg-type]
    bridge._on_notification(None, 1, SSE_NOTIFICATION_CHANNEL, valid)  # type: ignore[arg-type]
    bridge._on_notification(None, 1, SSE_NOTIFICATION_CHANNEL, valid)  # type: ignore[arg-type]

    assert bridge._parse_notification("not-json") is None
    assert bridge._parse_notification("[]") is None
    assert bridge._parse_notification('{"tenant_id":"tenant-a","sequence":true}') is None
    assert bridge._overflowed is True
    assert ("notification", "invalid_payload", 1) in metrics.calls
    assert ("notification", "queue_overflow", 1) in metrics.calls


def test_notification_bridge_coalesces_each_tenant_to_the_highest_sequence() -> None:
    class Metrics:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int]] = []

        def observe_sse(self, operation: str, outcome: str, count: int = 1) -> None:
            self.calls.append((operation, outcome, count))

        def set_sse_gauge(self, _metric: str, _value: int) -> None:
            return None

    metrics = Metrics()
    bridge = PostgresSSENotificationBridge(
        "postgresql+asyncpg://user:password@localhost/database",
        SSEBroker(InMemorySSEReplayLog()),
        queue_size=8,
        metrics=metrics,
    )
    bridge._queue.put_nowait(SSENotification("tenant-a", 1, 10.0))
    bridge._queue.put_nowait(SSENotification("tenant-b", 4, 11.0))
    bridge._queue.put_nowait(SSENotification("tenant-a", 3, 12.0))
    bridge._queue.put_nowait(SSENotification("tenant-a", 2, 13.0))

    pending = bridge._coalesce_pending_notifications(bridge._queue.get_nowait())

    assert [(item.tenant_id, item.sequence) for item in pending.values()] == [
        ("tenant-a", 3),
        ("tenant-b", 4),
    ]
    assert pending["tenant-a"].received_at == 10.0
    assert ("notification", "coalesced", 1) in metrics.calls
