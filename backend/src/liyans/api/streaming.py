from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypeVar

from liyans.core.async_cleanup import complete_cleanup
from liyans.core.tenant import TenantContext, tenant_scope

T = TypeVar("T")


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
