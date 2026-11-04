"""Shared helpers for integration tests: users, organisations and memberships."""

import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

PASSWORD = "correct horse battery staple"
COOKIE = "sia_session"


async def signup(
    client: httpx.AsyncClient, email: str = "alice@example.com", org: str = "Acme"
) -> dict[str, Any]:
    response = await client.post(
        "/auth/signup",
        json={"email": email, "password": PASSWORD, "name": "Alice", "organization_name": org},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


@dataclass
class Actor:
    """A logged-in user with their own browser (cookie jar)."""

    client: httpx.AsyncClient
    user_id: uuid.UUID
    org_id: uuid.UUID  # the organisation created at signup


async def make_actor(client: httpx.AsyncClient, email: str, org: str) -> Actor:
    me = await signup(client, email=email, org=org)
    return Actor(client, uuid.UUID(me["user"]["id"]), uuid.UUID(me["active_organization"]["id"]))


async def add_member(
    owner_engine: AsyncEngine, org_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO memberships (organization_id, user_id, role) VALUES (:o, :u, :r)"),
            {"o": org_id, "u": user_id, "r": role},
        )


async def switch(actor: Actor, org_id: uuid.UUID) -> httpx.Response:
    return await actor.client.put(
        "/auth/session/organization", json={"organization_id": str(org_id)}
    )
