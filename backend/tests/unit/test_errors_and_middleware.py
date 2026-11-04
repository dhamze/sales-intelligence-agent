"""The API's error contract: every failure returns the same JSON shape, carries a request ID,
and never leaks internal details."""

import httpx
from fastapi import FastAPI

from sia.core.errors import ConflictError, NotFoundError
from sia.main import create_app
from tests.conftest import SettingsFactory


def _add_failing_routes(app: FastAPI) -> None:
    @app.get("/test/crash")
    async def crash() -> None:
        raise RuntimeError("internal detail: password=hunter2 at /srv/app/secret.py")

    @app.get("/test/not-found")
    async def not_found() -> None:
        raise NotFoundError("Company not found.")

    @app.get("/test/conflict")
    async def conflict() -> None:
        raise ConflictError("Domain already exists.", details=[{"field": "domain"}])

    @app.get("/test/items/{item_id}")
    async def item(item_id: int, limit: int = 10) -> dict[str, int]:
        return {"item_id": item_id, "limit": limit}


async def test_unhandled_exception_returns_generic_500_without_leaking_details(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    _add_failing_routes(app)

    response = await client.get("/test/crash")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert error["message"] == "An unexpected error occurred."
    assert "hunter2" not in response.text
    assert "secret.py" not in response.text
    assert error["request_id"] == response.headers["x-request-id"]


async def test_app_errors_map_to_their_status_and_code(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    _add_failing_routes(app)

    not_found = await client.get("/test/not-found")
    conflict = await client.get("/test/conflict")

    assert not_found.status_code == 404
    assert not_found.json()["error"]["code"] == "not_found"
    assert not_found.json()["error"]["message"] == "Company not found."
    assert conflict.status_code == 409
    assert conflict.json()["error"]["details"] == [{"field": "domain"}]


async def test_validation_errors_use_the_standard_shape(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    _add_failing_routes(app)

    response = await client.get("/test/items/abc", params={"limit": "many"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert {tuple(d["loc"]) for d in error["details"]} == {("path", "item_id"), ("query", "limit")}


async def test_unknown_route_and_wrong_method(client: httpx.AsyncClient) -> None:
    missing = await client.get("/does-not-exist")
    wrong_method = await client.post("/health/live")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"


async def test_request_id_is_generated_when_absent(client: httpx.AsyncClient) -> None:
    first = await client.get("/health/live")
    second = await client.get("/health/live")

    assert len(first.headers["x-request-id"]) == 32
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


async def test_well_formed_caller_request_id_is_propagated(client: httpx.AsyncClient) -> None:
    response = await client.get("/does-not-exist", headers={"X-Request-ID": "lb-trace.42_a-b"})

    assert response.headers["x-request-id"] == "lb-trace.42_a-b"
    assert response.json()["error"]["request_id"] == "lb-trace.42_a-b"


async def test_malformed_caller_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    hostile = 'x" injected="true'
    response = await client.get("/health/live", headers={"X-Request-ID": hostile})

    assert response.headers["x-request-id"] != hostile
    assert len(response.headers["x-request-id"]) == 32


async def test_api_docs_are_disabled_in_production(make_settings: SettingsFactory) -> None:
    app = create_app(make_settings(SIA_ENV="production"))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
    ):
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404
