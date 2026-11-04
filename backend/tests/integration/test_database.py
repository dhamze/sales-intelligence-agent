import asyncio

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sia.core.config import Settings
from sia.core.db import create_engine
from tests.integration.conftest import alembic_config


async def _installed_extensions(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT extname FROM pg_extension"))
        return {row[0] for row in rows}


async def _current_revision(engine: AsyncEngine) -> str | None:
    async with engine.connect() as conn:
        row = await conn.execute(text("SELECT version_num FROM alembic_version"))
        return row.scalar_one_or_none()


async def test_database_is_migrated_to_head(
    owner_engine: AsyncEngine, test_settings: Settings
) -> None:
    head = ScriptDirectory.from_config(alembic_config(test_settings)).get_current_head()

    assert await _current_revision(owner_engine) == head


async def test_required_extensions_are_installed(engine: AsyncEngine) -> None:
    assert {"vector", "pg_trgm"} <= await _installed_extensions(engine)


async def test_pgvector_similarity_works(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        distance = await conn.scalar(text("SELECT '[1,0,0]'::vector <-> '[0,1,0]'::vector"))

    assert distance == pytest.approx(2**0.5)


def test_models_and_migrations_are_in_sync(test_settings: Settings) -> None:
    """Fails if an ORM model was changed without generating a migration."""
    command.check(alembic_config(test_settings))


def test_migrations_downgrade_and_upgrade_cleanly(test_settings: Settings) -> None:
    """Every migration must be reversible: down to an empty database, then back to head.

    Synchronous on purpose: Alembic runs its own event loop, which cannot start inside an
    async test's loop.
    """
    config = alembic_config(test_settings)

    async def extensions() -> set[str]:
        engine = create_engine(test_settings)
        try:
            return await _installed_extensions(engine)
        finally:
            await engine.dispose()

    command.downgrade(config, "base")
    assert "vector" not in asyncio.run(extensions())

    command.upgrade(config, "head")
    assert {"vector", "pg_trgm"} <= asyncio.run(extensions())
