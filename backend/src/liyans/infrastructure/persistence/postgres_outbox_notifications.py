from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

import asyncpg
from sqlalchemy.engine import make_url

from liyans.core.async_cleanup import complete_cleanup
from liyans.infrastructure.persistence.postgres_outbox import (
    OUTBOX_WAKE_CHANNEL,
    OUTBOX_WAKE_PAYLOAD,
)

logger = logging.getLogger(__name__)
ConnectFactory = Callable[[str], Awaitable[asyncpg.Connection]]
WakeCallback = Callable[[], None]


class OutboxWakeMetricsObserver(Protocol):
    def observe_outbox(self, operation: str, outcome: str, count: int = 1) -> None: ...

    def set_outbox_gauge(self, metric: str, value: int) -> None: ...


async def _connect(dsn: str) -> asyncpg.Connection:
    return await asyncpg.connect(dsn=dsn, command_timeout=10)


class PostgresOutboxWakeListener:
    """Turns transaction-bound PostgreSQL hints into idempotent publisher wakes."""

    def __init__(
        self,
        database_url: str,
        wake: WakeCallback,
        *,
        reconnect_base_seconds: float = 0.25,
        reconnect_max_seconds: float = 10.0,
        startup_timeout_seconds: float = 5.0,
        connect_factory: ConnectFactory | None = None,
        metrics: OutboxWakeMetricsObserver | None = None,
    ) -> None:
        if min(reconnect_base_seconds, reconnect_max_seconds, startup_timeout_seconds) <= 0:
            raise ValueError("Outbox wake listener timing settings must be positive")
        if reconnect_base_seconds > reconnect_max_seconds:
            raise ValueError("Outbox wake reconnect base cannot exceed its maximum")
        url = make_url(database_url)
        if url.drivername != "postgresql+asyncpg":
            raise ValueError("Outbox wake notifications require a postgresql+asyncpg URL")
        self._dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
        self._wake = wake
        self._reconnect_base = reconnect_base_seconds
        self._reconnect_max = reconnect_max_seconds
        self._startup_timeout = startup_timeout_seconds
        self._connect = connect_factory or _connect
        self._metrics = metrics
        self._stopping = asyncio.Event()
        self._connected = asyncio.Event()
        self._ready = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    async def start(self, *, wait_for_ready: bool = True) -> None:
        if self.running:
            return
        self._stopping.clear()
        self._ready.clear()
        self._task = asyncio.create_task(self._run(), name="outbox-postgres-wake-listener")
        if not wait_for_ready:
            return
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=self._startup_timeout)
        except TimeoutError:
            await self.close()
            raise RuntimeError("PostgreSQL Outbox wake listener did not become ready") from None

    async def close(self) -> None:
        self._stopping.set()
        task = self._task
        if task is None:
            return
        try:
            await complete_cleanup(self._stop_task(task))
        finally:
            self._task = None
            self._connected.clear()
            self._ready.clear()
            self._set_connected_gauge()

    async def _stop_task(self, task: asyncio.Task[None]) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=max(5.0, self._startup_timeout))
        except TimeoutError:
            task.cancel()
            await complete_cleanup(asyncio.gather(task, return_exceptions=True))

    async def _run(self) -> None:
        delay = self._reconnect_base
        while not self._stopping.is_set():
            connection: asyncpg.Connection | None = None
            try:
                connection = await self._connect(self._dsn)
                await connection.add_listener(OUTBOX_WAKE_CHANNEL, self._on_notification)
                self._connected.set()
                self._last_error = None
                self._observe("wake_listener", "connected")
                self._set_connected_gauge()
                self._wake()
                self._ready.set()
                self._observe("wake_listener", "ready")
                delay = self._reconnect_base
                await self._consume(connection)
                if not self._stopping.is_set():
                    raise ConnectionError("PostgreSQL Outbox wake listener connection closed")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = type(exc).__name__
                self._observe("wake_listener", "connection_error")
                logger.exception("PostgreSQL Outbox wake listener failed; reconnecting")
            finally:
                self._connected.clear()
                self._set_connected_gauge()
                if connection is not None and not connection.is_closed():
                    await complete_cleanup(self._close_connection(connection))
            if not self._stopping.is_set():
                await asyncio.sleep(delay)
                delay = min(self._reconnect_max, delay * 2)

    async def _consume(self, connection: asyncpg.Connection) -> None:
        while not self._stopping.is_set() and not connection.is_closed():
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=0.5)
            except TimeoutError:
                continue

    async def _close_connection(self, connection: asyncpg.Connection) -> None:
        try:
            await connection.remove_listener(OUTBOX_WAKE_CHANNEL, self._on_notification)
        finally:
            await connection.close(timeout=2)

    def _on_notification(
        self,
        _connection: asyncpg.Connection,
        _process_id: int,
        channel: str,
        payload: str,
    ) -> None:
        if channel != OUTBOX_WAKE_CHANNEL or payload != OUTBOX_WAKE_PAYLOAD:
            self._observe("wake_listener", "invalid_payload")
            return
        self._wake()
        self._observe("wake_listener", "received")

    def _observe(self, operation: str, outcome: str) -> None:
        if self._metrics is not None:
            self._metrics.observe_outbox(operation, outcome)

    def _set_connected_gauge(self) -> None:
        if self._metrics is not None:
            self._metrics.set_outbox_gauge(
                "wake_listener_connected",
                1 if self._connected.is_set() else 0,
            )
