"""Health endpoint logic, with the database simulated (see integration tests for the real one)."""

import asyncio

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from sia.modules.health import router as health


async def test_liveness_does_not_touch_the_database(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_if_called(engine: AsyncEngine) -> None:
        raise AssertionError("liveness must not check dependencies")

    monkeypatch.setattr(health, "ping", fail_if_called)

    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_ok_when_database_responds(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def healthy(engine: AsyncEngine) -> None:
        return None

    monkeypatch.setattr(health, "ping", healthy)

    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


async def test_readiness_503_when_database_errors_without_leaking_cause(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refused(engine: AsyncEngine) -> None:
        raise ConnectionRefusedError("connect to 10.0.0.5:5432 refused")

    monkeypatch.setattr(health, "ping", refused)

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"database": "unavailable"}}
    assert "10.0.0.5" not in response.text


async def test_readiness_503_when_database_hangs(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hangs(engine: AsyncEngine) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(health, "ping", hangs)
    monkeypatch.setattr(health, "READINESS_TIMEOUT_SECONDS", 0.05)

    response = await client.get("/health/ready")

    assert response.status_code == 503
