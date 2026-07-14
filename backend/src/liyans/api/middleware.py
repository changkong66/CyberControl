from __future__ import annotations

import re
import secrets
from uuid import UUID

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from liyans.api.errors import error_response
from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.infrastructure.observability.context import (
    MessageTraceContext,
    reset_message_trace,
    set_message_trace,
)

TRACE_PATTERN = re.compile(r"^[a-fA-F0-9]{16,64}$")


class TenantTraceMiddleware(BaseHTTPMiddleware):
    """Consumes identity headers supplied by the trusted authentication gateway."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        try:
            return await self._dispatch_scoped(request, call_next)
        except LiyanError as exc:
            return error_response(request, exc)

    async def _dispatch_scoped(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        trace_id = request.headers.get("x-trace-id", "")
        if not TRACE_PATTERN.fullmatch(trace_id):
            trace_id = secrets.token_hex(16)
        request.state.trace_id = trace_id

        if not request.url.path.startswith("/internal/"):
            token = set_message_trace(MessageTraceContext(trace_id, None, None, None))
            try:
                response = await call_next(request)
            finally:
                reset_message_trace(token)
            response.headers["x-trace-id"] = trace_id
            return response

        tenant_id = request.headers.get("x-tenant-id")
        subject_ref = request.headers.get("x-subject-ref")
        if not tenant_id or not subject_ref:
            raise LiyanError(
                ErrorCode.TENANT_CONTEXT_MISSING,
                "Trusted tenant and subject headers are required.",
                category=ErrorCategory.TENANT,
                status_code=403,
            )
        session_value = request.headers.get("x-session-id")
        try:
            session_id = UUID(session_value) if session_value else None
        except ValueError as exc:
            raise LiyanError(
                ErrorCode.CONTRACT_INVALID,
                "The session identity is invalid.",
                category=ErrorCategory.CONTRACT,
                status_code=422,
            ) from exc
        roles = frozenset(filter(None, request.headers.get("x-roles", "").split(",")))
        scopes = frozenset(filter(None, request.headers.get("x-scopes", "").split(",")))
        context = TenantContext(
            tenant_id=tenant_id,
            subject_ref=subject_ref,
            roles=roles,
            scopes=scopes,
            trace_id=trace_id,
            session_id=session_id,
        )
        token = set_message_trace(MessageTraceContext(trace_id, None, None, tenant_id))
        try:
            with tenant_scope(context):
                response = await call_next(request)
        finally:
            reset_message_trace(token)
        response.headers["x-trace-id"] = trace_id
        return response
