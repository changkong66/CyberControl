from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MessageTraceContext:
    trace_id: str
    span_id: str | None
    envelope_id: str | None
    tenant_id: str | None


_message_trace: ContextVar[MessageTraceContext | None] = ContextVar(
    "liyans_message_trace",
    default=None,
)


def current_message_trace() -> MessageTraceContext | None:
    return _message_trace.get()


def set_message_trace(context: MessageTraceContext) -> Token[MessageTraceContext | None]:
    return _message_trace.set(context)


def reset_message_trace(token: Token[MessageTraceContext | None]) -> None:
    _message_trace.reset(token)
