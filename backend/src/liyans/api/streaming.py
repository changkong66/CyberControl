from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from liyans.core.async_cleanup import complete_cleanup
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.infrastructure.streaming.sse import SSEEvent, encode_sse_frame

T = TypeVar("T")


class TenantScopedSSEStream(AsyncIterator[bytes]):
    """Explicit response iterator that is the sole owner of one SSE subscription."""

    def __init__(
        self,
        request: Any,
        subscription: AsyncIterator[SSEEvent | None],
        context: TenantContext,
        cursor_codec: Any,
    ) -> None:
        self._request = request
        self._subscription = subscription
        self._context = context
        self._cursor_codec = cursor_codec
        self._close_lock = asyncio.Lock()
        self._closed = False
        self._disconnect_poll_seconds = 0.5
        self._disconnect_task: asyncio.Task[None] | None = None

    def __aiter__(self) -> TenantScopedSSEStream:
        return self

    async def __anext__(self) -> bytes:
        if self._closed:
            raise StopAsyncIteration
        self._ensure_disconnect_watcher()
        try:
            while True:
                if await self._request.is_disconnected():
                    await self._close_from_advance()
                    raise StopAsyncIteration
                event = await next_tenant_scoped_event(
                    self._subscription,
                    self._context,
                )
                if await self._request.is_disconnected():
                    await self._close_from_advance()
                    raise StopAsyncIteration
                if event is None:
                    return b": heartbeat\n\n"
                cursor = self._cursor_codec.encode(
                    self._context.tenant_id,
                    event.sequence,
                )
                return encode_sse_frame(event, cursor)
        except StopAsyncIteration:
            self._closed = True
            await self._stop_disconnect_watcher()
            raise
        except asyncio.CancelledError:
            await complete_cleanup(self._close_from_advance())
            raise

    def _ensure_disconnect_watcher(self) -> None:
        if self._disconnect_task is None:
            self._disconnect_task = asyncio.create_task(
                self._watch_disconnect(),
                name="sse-disconnect-watcher",
            )

    async def _watch_disconnect(self) -> None:
        while not self._closed:
            if await self._request.is_disconnected():
                await self.aclose()
                return
            await asyncio.sleep(self._disconnect_poll_seconds)

    async def _stop_disconnect_watcher(self) -> None:
        task = self._disconnect_task
        self._disconnect_task = None
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        await complete_cleanup(asyncio.gather(task, return_exceptions=True))

    async def _close_from_advance(self) -> None:
        if self._closed:
            await self._stop_disconnect_watcher()
            return
        self._closed = True
        await close_subscription(self._subscription)
        await self._stop_disconnect_watcher()

    async def aclose(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            await close_subscription(self._subscription)
            await self._stop_disconnect_watcher()


async def next_tenant_scoped_event(
    subscription: AsyncIterator[T],
    context: TenantContext,
) -> T:
    """Advance a subscription with tenant context, then release it before a yield."""

    with tenant_scope(context):
        return await anext(subscription)


async def close_subscription(subscription: Any) -> None:
    """Close an async subscription even when its request task was cancelled."""

    close = getattr(subscription, "aclose", None)
    if close is None:
        return
    await complete_cleanup(close())


@asynccontextmanager
async def managed_subscription(subscription: Any) -> AsyncIterator[AsyncIterator[Any]]:
    """Use an explicit subscription owner while retaining iterator compatibility in tests."""

    enter = getattr(subscription, "__aenter__", None)
    exit_context = getattr(subscription, "__aexit__", None)
    if enter is not None and exit_context is not None:
        async with subscription as managed:
            yield managed
        return
    try:
        yield subscription
    finally:
        await close_subscription(subscription)
