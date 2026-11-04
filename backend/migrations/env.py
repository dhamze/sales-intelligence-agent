"""Alembic migration environment.

The database URL comes from application Settings (environment / `.env`), never from
alembic.ini. Tests can supply their own Settings via `config.attributes["settings"]`.
"""

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import sia.models  # noqa: F401  # registers every module's tables on Base.metadata
from sia.core.config import Settings, get_settings
from sia.core.db import Base
from sia.core.logging import configure_logging

config = context.config
settings: Settings = config.attributes.get("settings") or get_settings()
if "settings" not in config.attributes:  # tests configure logging themselves
    configure_logging(settings.log_level, settings.log_format)

target_metadata = Base.metadata

_COMPARE_OPTIONS = {"compare_type": True, "compare_server_default": True}


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it (`alembic upgrade head --sql`)."""
    context.configure(
        url=settings.migration_database_url.render_as_string(hide_password=True),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_COMPARE_OPTIONS,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, **_COMPARE_OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(settings.migration_database_url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
