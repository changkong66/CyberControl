from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError, TenantIsolationError


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: str
    subject_ref: str
    roles: frozenset[str]
    scopes: frozenset[str]
    trace_id: str
    session_id: UUID | None = None


_tenant_context: ContextVar[TenantContext | None] = ContextVar(
    "liyans_tenant_context",
    default=None,
)


def current_tenant() -> TenantContext:
    context = _tenant_context.get()
    if context is None:
        raise LiyanError(
            ErrorCode.TENANT_CONTEXT_MISSING,
            "Tenant context is required.",
            category=ErrorCategory.TENANT,
            status_code=403,
        )
    return context


def assert_tenant(tenant_id: str) -> TenantContext:
    context = current_tenant()
    if context.tenant_id != tenant_id:
        raise TenantIsolationError
    return context


@contextmanager
def tenant_scope(context: TenantContext) -> Iterator[TenantContext]:
    token: Token[TenantContext | None] = _tenant_context.set(context)
    try:
        yield context
    finally:
        _tenant_context.reset(token)
