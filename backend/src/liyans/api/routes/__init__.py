"""FastAPI route modules."""

from .identity import (
    account_router,
    public_router,
    tenant_account_router,
    tenant_registration_router,
)

__all__ = [
    "account_router",
    "public_router",
    "tenant_account_router",
    "tenant_registration_router",
]
