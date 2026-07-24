from __future__ import annotations

import asyncio
from collections.abc import Awaitable


async def complete_cleanup(awaitable: Awaitable[object]) -> None:
    """Finish asynchronous cleanup before re-propagating task cancellation."""

    cleanup = asyncio.ensure_future(awaitable)
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
    await cleanup
    if cancelled:
        raise asyncio.CancelledError
