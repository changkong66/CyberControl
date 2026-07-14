from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import asyncpg
from sqlalchemy.engine import make_url

from liyans.core.tenant import TenantContext, tenant_scope
from liyans.infrastructure.streaming.sse import SSEBroker, SSEMetricsObserver

logger = logging.getLogger(__name__)

SSE_NOTIFICATION_CHANNEL = "liyans_sse_events_v1"
TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
ConnectFactory = Callable[[str], Awaitable[asyncpg.Connection]]


@dataclass(frozen=True, slots=True)
class SSENotification:
    tenant_id: str
    sequence: int


async def _connect(dsn: str) -> asyncpg.Connection:
    return await asyncpg.connect(dsn=dsn, command_timeout=10)


class PostgresSSENotificationBridge:
    """Bridges committed PostgreSQL SSE rows to subscribers on every API instance."""

    def __init__(
        self,
        database_url: str,
        broker: SSEBroker,
        *,
        queue_size: int = 1024,
        reconnect_base_seconds: float = 0.25,
        reconnect_max_seconds: float = 10.0,
        startup_timeout_seconds: float = 5.0,
        connect_factory: ConnectFactory | None = None,
        metrics: SSEMetricsObserver | None = None,
    ) -> None:
        if queue_size < 1:
            raise ValueError("SSE notification queue_size must be positive")
        if (
            min(
                reconnect_base_seconds,
                reconnect_max_seconds,
                startup_timeout_seconds,
            )
            <= 0
        ):
            raise ValueError("SSE notification timing settings must be positive")
        if reconnect_base_seconds > reconnect_max_seconds:
            raise ValueError("SSE reconnect base cannot exceed its maximum")
        url = make_url(database_url)
        if url.drivername != "postgresql+asyncpg":
            raise ValueError("SSE notifications require a postgresql+asyncpg URL")
        self._dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
        self._broker = broker
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=queue_size)
        self._reconnect_base = reconnect_base_seconds
        self._reconnect_max = reconnect_max_seconds
        self._startup_timeout = startup_timeout_seconds
        self._connect = connect_factory or _connect
        self._metrics = metrics
        self._stopping = asyncio.Event()
        self._connected = asyncio.Event()
        self._overflowed = False
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

    async def start(self) -> None:
        if self.running:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="sse-postgres-listener")
        try:
            await asyncio.wait_for(
                self._connected.wait(),
                timeout=self._startup_timeout,
            )
        except TimeoutError:
            await self.close()
            raise RuntimeError(
                "PostgreSQL SSE notification listener did not become ready"
            ) from None

    async def close(self) -> None:
        self._stopping.set()
        task = self._task
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self._task = None
        self._connected.clear()

    async def synchronize_active_tenants(self) -> int:
        delivered = 0
        for tenant_id in self._broker.active_tenants():
            delivered += await self._synchronize(tenant_id)
        return delivered

    async def _run(self) -> None:
        delay = self._reconnect_base
        while not self._stopping.is_set():
            connection: asyncpg.Connection | None = None
            try:
                connection = await self._connect(self._dsn)
                await connection.add_listener(
                    SSE_NOTIFICATION_CHANNEL,
                    self._on_notification,
                )
                self._connected.set()
                self._last_error = None
                self._observe("notification", "connected")
                await self.synchronize_active_tenants()
                delay = self._reconnect_base
                await self._consume(connection)
                if not self._stopping.is_set():
                    raise ConnectionError("PostgreSQL SSE listener connection closed")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = type(exc).__name__
                self._observe("notification", "connection_error")
                logger.exception("PostgreSQL SSE notification bridge failed; reconnecting")
            finally:
                self._connected.clear()
                if connection is not None and not connection.is_closed():
                    try:
                        await connection.remove_listener(
                            SSE_NOTIFICATION_CHANNEL,
                            self._on_notification,
                        )
                    finally:
                        await connection.close(timeout=2)
            if not self._stopping.is_set():
                await asyncio.sleep(delay)
                delay = min(self._reconnect_max, delay * 2)

    async def _consume(self, connection: asyncpg.Connection) -> None:
        while not self._stopping.is_set() and not connection.is_closed():
            if self._overflowed:
                self._overflowed = False
                await self.synchronize_active_tenants()
                self._observe("notification", "overflow_recovered")
            try:
                payload = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except TimeoutError:
                continue
            notification = self._parse_notification(payload)
            if notification is None:
                self._observe("notification", "invalid_payload")
                continue
            await self._synchronize(
                notification.tenant_id,
                through_sequence=notification.sequence,
            )
            self._observe("notification", "processed")

    def _on_notification(
        self,
        _connection: asyncpg.Connection,
        _process_id: int,
        channel: str,
        payload: str,
    ) -> None:
        if channel != SSE_NOTIFICATION_CHANNEL or len(payload.encode("utf-8")) > 1024:
            self._observe("notification", "invalid_payload")
            return
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            self._overflowed = True
            self._observe("notification", "queue_overflow")

    async def _synchronize(
        self,
        tenant_id: str,
        *,
        through_sequence: int | None = None,
    ) -> int:
        context = TenantContext(
            tenant_id=tenant_id,
            subject_ref="system:sse-notification-bridge",
            roles=frozenset({"system:sse-bridge"}),
            scopes=frozenset({"topic3:sse:read"}),
            trace_id="0" * 32,
        )
        with tenant_scope(context):
            return await self._broker.synchronize(
                tenant_id,
                through_sequence=through_sequence,
            )

    @staticmethod
    def _parse_notification(payload: str) -> SSENotification | None:
        try:
            document: Any = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(document, dict) or set(document) != {"tenant_id", "sequence"}:
            return None
        tenant_id = document.get("tenant_id")
        sequence = document.get("sequence")
        if (
            not isinstance(tenant_id, str)
            or not TENANT_ID_PATTERN.fullmatch(tenant_id)
            or not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 0
        ):
            return None
        return SSENotification(tenant_id=tenant_id, sequence=sequence)

    def _observe(self, operation: str, outcome: str, count: int = 1) -> None:
        if self._metrics is not None and count > 0:
            self._metrics.observe_sse(operation, outcome, count)
