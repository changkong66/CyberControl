from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import Token
from typing import Protocol

from liyans_contracts.envelope import Topic3EnvelopeV1

from liyans.core.tenant import assert_tenant
from liyans.infrastructure.observability.context import (
    MessageTraceContext,
    reset_message_trace,
    set_message_trace,
)

NextHandler = Callable[[Topic3EnvelopeV1], Awaitable[None]]


class MessageMiddleware(Protocol):
    async def __call__(
        self,
        envelope: Topic3EnvelopeV1,
        call_next: NextHandler,
    ) -> None: ...


class TenantBoundaryMiddleware:
    async def __call__(
        self,
        envelope: Topic3EnvelopeV1,
        call_next: NextHandler,
    ) -> None:
        assert_tenant(envelope.tenant_id)
        await call_next(envelope)


class TraceMessageMiddleware:
    async def __call__(
        self,
        envelope: Topic3EnvelopeV1,
        call_next: NextHandler,
    ) -> None:
        token: Token[MessageTraceContext | None] = set_message_trace(
            MessageTraceContext(
                trace_id=envelope.trace_id,
                span_id=envelope.span_id,
                envelope_id=str(envelope.envelope_id),
                tenant_id=envelope.tenant_id,
            )
        )
        try:
            await call_next(envelope)
        finally:
            reset_message_trace(token)


def compose_middleware(
    middleware: list[MessageMiddleware],
    terminal: NextHandler,
) -> NextHandler:
    handler = terminal
    for current in reversed(middleware):
        next_handler = handler

        async def wrapped(
            envelope: Topic3EnvelopeV1,
            current: MessageMiddleware = current,
            next_handler: NextHandler = next_handler,
        ) -> None:
            await current(envelope, next_handler)

        handler = wrapped
    return handler
