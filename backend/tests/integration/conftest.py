"""Integration test fixtures: a real PostgreSQL test database.

Connection details come from the environment / `.env` (CI sets them as env vars), but the
database name is always forced to `sia_test`, so tests can never wipe development data.

Two database roles are used, exactly as in production:
- `engine`       — the restricted runtime role `sia_app`. Code under test uses this, so RLS
                   is really enforced in tests.
- `owner_engine` — the schema owner (a superuser locally). Only for test setup/teardown that
                   must bypass RLS, e.g. creating two tenants' data.

The schema is dropped and rebuilt from migrations once per session; table rows are wiped
before every test.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

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
    base = Settings()  # credentials from environment / .env
    return base.model_copy(
        update={
            "env": "test",
            "postgres_db": TEST_DATABASE,
            "log_level": "WARNING",
            # Never call the real AI API or the live web from tests, even if .env has a key.
            "llm_provider": "fake",
            "fetch_provider": "fake",
            "anthropic_api_key": None,
        }
    )


def alembic_config(settings: Settings) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["settings"] = settings
    return config


def create_owner_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.migration_database_url, poolclass=pool.NullPool)


async def _reset_schema(settings: Settings) -> None:
    engine = create_owner_engine(settings)
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
async def owner_engine(test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_owner_engine(test_settings)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_tables(owner_engine: AsyncEngine) -> None:
    """Start every test with empty tables (schema and migration history are kept)."""
    async with owner_engine.begin() as conn:
        tables = (
            (
                await conn.execute(
                    text(
                        "SELECT quote_ident(tablename) FROM pg_tables "
                        "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                    )
                )
            )
            .scalars()
            .all()
        )
        if tables:
            await conn.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))


@pytest.fixture
async def engine(test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Runtime engine: connects as the restricted `sia_app` role, like the real API."""
    engine = create_engine(test_settings)
    yield engine
    await engine.dispose()


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    """Overrides the unit-test app: this one talks to the real test database."""
    return create_app(test_settings)


ClientFactory = Callable[[], httpx.AsyncClient]


@pytest.fixture
async def make_client(app: FastAPI, client: httpx.AsyncClient) -> AsyncIterator[ClientFactory]:
    """Extra independent HTTP clients (separate cookie jars = separate browsers) for the same
    app. Depends on `client` so the app's lifespan is already running."""
    clients: list[httpx.AsyncClient] = []

    def factory() -> httpx.AsyncClient:
        new = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        clients.append(new)
        return new

    yield factory
    for c in clients:
        await c.aclose()
