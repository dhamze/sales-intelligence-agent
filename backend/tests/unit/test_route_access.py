"""Guard test: every API operation refuses anonymous callers unless it is explicitly public.

Operations are listed from the app's own OpenAPI description, so a newly added route is checked
automatically: forgetting its authentication dependency fails this test. (Admin-only routes have
behavioural tests of their own; data isolation between organisations is enforced by RLS.)
"""

import re
import uuid

import httpx
import pytest
from fastapi import FastAPI

# (method, path) pairs anyone may call. Keep this list short and justified.
PUBLIC = {
    ("GET", "/health/live"),  # probes
    ("GET", "/health/ready"),
    ("POST", "/auth/signup"),  # creating an account / logging in
    ("POST", "/auth/login"),
    ("POST", "/auth/logout"),  # harmless without a session
}


def operations(app: FastAPI) -> list[tuple[str, str]]:
    return sorted(
        (method.upper(), path)
        for path, item in app.openapi()["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    )


def test_the_operation_list_is_complete(app: FastAPI) -> None:
    ops = operations(app)
    assert len(ops) > 25  # sanity: the description really lists the API
    assert set(ops) >= PUBLIC  # no stale entries in the public list


@pytest.mark.parametrize("method_path", sorted(PUBLIC))
def test_public_list_is_explicit(method_path: tuple[str, str]) -> None:
    _method, path = method_path
    assert path.startswith(("/health/", "/auth/")), "only health and auth may be public"


async def test_every_other_operation_requires_login(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    refused: dict[tuple[str, str], int] = {}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        for method, path in operations(app):
            if (method, path) in PUBLIC:
                continue
            url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
            body: dict[str, object] | None = {} if method in {"POST", "PUT", "PATCH"} else None
            response = await client.request(method, url, json=body)
            refused[(method, path)] = response.status_code

    not_401 = {op: status for op, status in refused.items() if status != 401}
    assert not_401 == {}, f"reachable without logging in: {not_401}"
