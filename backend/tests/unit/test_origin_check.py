"""CSRF protection: state-changing requests from other sites are rejected."""

import httpx
import pytest
from fastapi import FastAPI


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    @app.post("/test/echo")
    async def echo() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/test/echo")
    async def echo_get() -> dict[str, bool]:
        return {"ok": True}

    return app


async def test_cross_site_post_is_blocked(client: httpx.AsyncClient) -> None:
    response = await client.post("/test/echo", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden_origin"
    assert response.headers["x-request-id"]  # still traced


@pytest.mark.parametrize(
    "origin", ["null", "http://localhost:5173.evil.example", "http://test.evil"]
)
async def test_lookalike_and_null_origins_are_blocked(
    client: httpx.AsyncClient, origin: str
) -> None:
    response = await client.post("/test/echo", headers={"Origin": origin})

    assert response.status_code == 403


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173/"])
async def test_allowed_frontend_origins_pass(client: httpx.AsyncClient, origin: str) -> None:
    response = await client.post("/test/echo", headers={"Origin": origin})

    assert response.status_code == 200


async def test_same_origin_post_passes(client: httpx.AsyncClient) -> None:
    response = await client.post("/test/echo", headers={"Origin": "http://test"})

    assert response.status_code == 200


async def test_non_browser_client_without_origin_passes(client: httpx.AsyncClient) -> None:
    assert (await client.post("/test/echo")).status_code == 200


async def test_safe_methods_are_not_checked(client: httpx.AsyncClient) -> None:
    response = await client.get("/test/echo", headers={"Origin": "https://evil.example"})

    assert response.status_code == 200
