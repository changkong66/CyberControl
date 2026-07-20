from __future__ import annotations

import re
import secrets
from dataclasses import replace
from uuid import UUID

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from liyans.api.errors import error_response
from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import tenant_scope
from liyans.infrastructure.observability.context import (
    MessageTraceContext,
    reset_message_trace,
    set_message_trace,
)

TRACE_PATTERN = re.compile(r"^[a-fA-F0-9]{16,64}$")
FORBIDDEN_IDENTITY_HEADERS = frozenset(
    {
        "x-tenant-id",
        "x-subject-ref",
        "x-user-id",
        "x-roles",
        "x-role",
        "x-scopes",
        "x-scope",
        "x-permissions",
        "x-auth-request-user",
        "x-auth-request-groups",
    }
)


class AuthenticationTenantMiddleware(BaseHTTPMiddleware):
    """Validates bearer identity before creating tenant and trace contexts."""

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

        if any(header in request.headers for header in FORBIDDEN_IDENTITY_HEADERS):
            raise LiyanError(
                ErrorCode.AUTH_IDENTITY_HEADER_FORBIDDEN,
                "Client-controlled identity headers are forbidden.",
                category=ErrorCategory.AUTH,
                status_code=400,
            )

        if not request.url.path.startswith("/internal/"):
            token = set_message_trace(MessageTraceContext(trace_id, None, None, None))
            try:
                response = await call_next(request)
            finally:
                reset_message_trace(token)
            response.headers["x-trace-id"] = trace_id
            return response

        token = self._bearer_token(request)
        verifier = getattr(request.app.state, "token_verifier", None)
        authorizer = getattr(request.app.state, "tenant_authorizer", None)
        if verifier is None or authorizer is None:
            raise LiyanError(
                ErrorCode.AUTH_CONFIG_INVALID,
                "Authentication services are unavailable.",
                category=ErrorCategory.AUTH,
                retriable=True,
                status_code=503,
            )
        principal = await verifier.verify(token)
        context = await authorizer.authorize(principal, trace_id=trace_id)

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
        context = replace(context, session_id=session_id)
        request.state.principal = principal
        trace_token = set_message_trace(
            MessageTraceContext(trace_id, None, None, context.tenant_id)
        )
        try:
            with tenant_scope(context):
                response = await call_next(request)
        finally:
            reset_message_trace(trace_token)
        response.headers["x-trace-id"] = trace_id
        return response

    @staticmethod
    def _bearer_token(request: Request) -> str:
        value = request.headers.get("authorization", "")
        scheme, separator, token = value.partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not token
            or token != token.strip()
            or any(character.isspace() for character in token)
        ):
            raise LiyanError(
                ErrorCode.AUTH_REQUIRED,
                "Bearer authentication is required.",
                category=ErrorCategory.AUTH,
                status_code=401,
            )
        return token
