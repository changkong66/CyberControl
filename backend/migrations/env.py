from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from liyans.core.settings import Settings
from liyans.domains.topic1 import models as topic1_models
from liyans.domains.topic2 import models as topic2_models
from liyans.infrastructure.database.models import Base

del topic1_models
del topic2_models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def migration_url() -> str:
    settings = Settings()
    url = settings.database_migration_url or settings.database_url
    if make_url(url).drivername != "postgresql+asyncpg":
        raise RuntimeError("Alembic requires a postgresql+asyncpg migration URL")
    return url


def configure_context(connection: Connection | None = None) -> None:
    options = {
        "target_metadata": target_metadata,
        "compare_type": True,
        "compare_server_default": True,
        "transaction_per_migration": True,
    }
    if connection is None:
        context.configure(
            url=migration_url(),
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            output_buffer=config.output_buffer,
            **options,
        )
    else:
        context.configure(connection=connection, **options)


def run_migrations_offline() -> None:
    configure_context()
    with context.begin_transaction():
        context.run_migrations()


def apply_migrations(connection: Connection) -> None:
    configure_context(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    config.set_main_option("sqlalchemy.url", migration_url().replace("%", "%%"))
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(apply_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
