"""Integration test fixtures: a real PostgreSQL test database.

Connection details come from the environment / `.env` (CI sets them as env vars), but the
database name is always forced to `sia_test`, so tests can never wipe development data.
The schema is dropped and rebuilt from migrations once per test session.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sia.core.config import Settings
from sia.core.db import create_engine
from sia.main import create_app

TEST_DATABASE = "sia_test"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Every test in this directory is an integration test."""
    here = Path(__file__).parent
    for item in items:
        if here in item.path.parents:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    base = Settings()
    return base.model_copy(
        update={"env": "test", "postgres_db": TEST_DATABASE, "log_level": "WARNING"}
    )


def alembic_config(settings: Settings) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["settings"] = settings
    return config


async def _reset_schema(settings: Settings) -> None:
    engine = create_engine(settings)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database(test_settings: Settings) -> Iterator[None]:
    assert test_settings.postgres_db == TEST_DATABASE  # never touch any other database
    try:
        asyncio.run(_reset_schema(test_settings))
    except OSError as exc:
        pytest.exit(
            f"Cannot reach PostgreSQL at {test_settings.postgres_host}:"
            f"{test_settings.postgres_port} ({exc!r}).\n"
            "Start it with `docker compose up -d db`, or run unit tests only with "
            "`pytest -m 'not integration'`.",
            returncode=1,
        )
    command.upgrade(alembic_config(test_settings), "head")
    yield


@pytest.fixture
async def engine(test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(test_settings)
    yield engine
    await engine.dispose()


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    """Overrides the unit-test app: this one talks to the real test database."""
    return create_app(test_settings)
