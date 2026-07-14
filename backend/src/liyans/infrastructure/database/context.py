from __future__ import annotations

from liyans.core.tenant import TenantContext, current_tenant
from liyans.infrastructure.database.session import SessionExecutionContext


def session_context_from_tenant(context: TenantContext) -> SessionExecutionContext:
    return SessionExecutionContext(
        tenant_id=context.tenant_id,
        subject_ref=context.subject_ref,
        trace_id=context.trace_id,
    )


def current_session_context() -> SessionExecutionContext:
    return session_context_from_tenant(current_tenant())
