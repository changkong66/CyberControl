from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.infrastructure.security.authentication import AuthenticatedPrincipal

AuthorizationDependency = Callable[[Request], Awaitable[AuthenticatedPrincipal]]


def require_scopes(*required_scopes: str) -> AuthorizationDependency:
    required = frozenset(required_scopes)

    async def authorize(request: Request) -> AuthenticatedPrincipal:
        principal = getattr(request.state, "principal", None)
        if not isinstance(principal, AuthenticatedPrincipal):
            raise LiyanError(
                ErrorCode.AUTH_REQUIRED,
                "Bearer authentication is required.",
                category=ErrorCategory.AUTH,
                status_code=401,
            )
        if not required <= principal.scopes:
            raise LiyanError(
                ErrorCode.AUTH_FORBIDDEN,
                "The authenticated identity lacks a required permission.",
                category=ErrorCategory.AUTH,
                status_code=403,
                details={"required_scopes": sorted(required)},
            )
        return principal

    return authorize
