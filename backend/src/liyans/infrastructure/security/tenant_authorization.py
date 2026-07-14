from __future__ import annotations

from typing import Protocol

from sqlalchemy import select

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext
from liyans.infrastructure.database.models import TenantModel, TenantStatus
from liyans.infrastructure.database.session import (
    DatabaseSessionManager,
    SessionExecutionContext,
)
from liyans.infrastructure.security.authentication import AuthenticatedPrincipal


class TenantAuthorizer(Protocol):
    async def authorize(
        self,
        principal: AuthenticatedPrincipal,
        *,
        trace_id: str,
    ) -> TenantContext: ...


class PostgresTenantAuthorizer:
    def __init__(self, database: DatabaseSessionManager) -> None:
        self._database = database

    async def authorize(
        self,
        principal: AuthenticatedPrincipal,
        *,
        trace_id: str,
    ) -> TenantContext:
        context = SessionExecutionContext(
            tenant_id=principal.tenant_id,
            subject_ref=principal.subject,
            trace_id=trace_id,
        )
        async with self._database.transaction(context=context) as session:
            result = await session.execute(
                select(TenantModel).where(TenantModel.tenant_id == principal.tenant_id)
            )
            tenant = result.scalar_one_or_none()
        if tenant is None:
            raise LiyanError(
                ErrorCode.AUTH_FORBIDDEN,
                "The authenticated identity is not authorized for this tenant.",
                category=ErrorCategory.AUTH,
                status_code=403,
            )
        if tenant.status != TenantStatus.ACTIVE.value:
            raise LiyanError(
                ErrorCode.TENANT_INACTIVE,
                "The tenant is not active.",
                category=ErrorCategory.TENANT,
                status_code=403,
            )
        if tenant.oidc_issuer is None or tenant.oidc_tenant_claim is None:
            raise LiyanError(
                ErrorCode.TENANT_IDENTITY_UNBOUND,
                "The tenant has no trusted OIDC identity binding.",
                category=ErrorCategory.TENANT,
                status_code=403,
            )
        if (
            tenant.oidc_issuer != principal.issuer
            or tenant.oidc_tenant_claim != principal.tenant_id
        ):
            raise LiyanError(
                ErrorCode.AUTH_FORBIDDEN,
                "The authenticated identity is not authorized for this tenant.",
                category=ErrorCategory.AUTH,
                status_code=403,
            )
        return TenantContext(
            tenant_id=tenant.tenant_id,
            subject_ref=principal.subject,
            roles=principal.roles,
            scopes=principal.scopes,
            trace_id=trace_id,
        )
