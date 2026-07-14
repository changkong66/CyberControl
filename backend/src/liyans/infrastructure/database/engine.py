from __future__ import annotations

import logging

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.settings import Settings

logger = logging.getLogger(__name__)


def create_database_engine(
    settings: Settings,
    *,
    database_url: str | None = None,
    application_name: str = "liyans-api",
) -> AsyncEngine:
    """Create the process-wide async engine; it does not open a connection."""

    if not application_name or len(application_name) > 63:
        raise ValueError("application_name must contain between one and 63 characters")
    url = make_url(database_url or settings.database_url)
    if url.drivername != "postgresql+asyncpg":
        raise LiyanError(
            ErrorCode.CONFIG_INVALID,
            "The database driver must be postgresql+asyncpg.",
            category=ErrorCategory.CONFIG,
            status_code=500,
        )

    server_settings = {
        "application_name": application_name,
        "timezone": "UTC",
        "statement_timeout": str(settings.database_statement_timeout_ms),
        "idle_in_transaction_session_timeout": str(settings.database_idle_transaction_timeout_ms),
    }
    engine = create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_recycle=settings.database_pool_recycle_seconds,
        connect_args={
            "command_timeout": settings.database_command_timeout_seconds,
            "server_settings": server_settings,
        },
    )
    logger.info(
        "Configured PostgreSQL async engine for host=%s database=%s",
        url.host,
        url.database,
    )
    return engine
