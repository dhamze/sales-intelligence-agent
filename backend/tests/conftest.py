"""Shared test fixtures.

- `app`    — an application instance. Unit tests get one pointing at a database that is never
             contacted; `integration/conftest.py` overrides it to use the real test database.
- `client` — an HTTP client that calls `app` in-process (no network, no server).
"""

import asyncio
import platform
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from sia.core.config import Settings
from sia.main import create_app

SettingsFactory = Callable[..., Settings]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live-llm",
        action="store_true",
        help="Run the live AI quality check (real Claude API + live websites; costs money).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-live-llm"):
        return
    skip = pytest.mark.skip(reason="live AI check: run with --run-live-llm (costs money)")
    for item in items:
        if "live_llm" in item.keywords:
            item.add_marker(skip)


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    """psycopg (used by the job queue) can't run on Windows' default Proactor event loop."""
    if platform.system() == "Windows":  # runtime check: both branches stay type-checked
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}


@pytest.fixture
def make_settings() -> SettingsFactory:
    """Build Settings from explicit values only: ignores `.env`, so unit tests behave the same
    on every machine. Keyword names are the environment variable names."""

    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "SIA_ENV": "test",
            "SIA_LOG_LEVEL": "WARNING",
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": 5432,
            "POSTGRES_USER": "unit",
            "POSTGRES_PASSWORD": "unit-password",
            "SIA_APP_DB_PASSWORD": "unit-app-password",
            "POSTGRES_DB": "sia_unit_no_db",
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return factory


@pytest.fixture
def app(make_settings: SettingsFactory) -> FastAPI:
    return create_app(make_settings())


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    # ASGITransport does not run startup/shutdown, so enter the app's lifespan explicitly.
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
