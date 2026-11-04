"""Organisation and member management through the API, including cross-tenant attempts.

World (built per test):
    Acme   (alice: owner, carol: member)
    Globex (bob: owner)
    carol also owns her own "Carol Co" from signup.
"""

import uuid
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import ClientFactory
from tests.integration.test_auth_api import signup


@dataclass
class Actor:
    client: httpx.AsyncClient
    user_id: uuid.UUID
    org_id: uuid.UUID  # the organisation created at signup


@dataclass
class World:
    alice: Actor
    bob: Actor
    carol: Actor


async def _actor(make_client: ClientFactory, email: str, org: str) -> Actor:
    client = make_client()
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


@pytest.fixture
async def world(make_client: ClientFactory, owner_engine: AsyncEngine) -> World:
    alice = await _actor(make_client, "alice@acme.example.com", "Acme")
    bob = await _actor(make_client, "bob@globex.example.com", "Globex")
    carol = await _actor(make_client, "carol@carol.example.com", "Carol Co")
    await add_member(owner_engine, alice.org_id, carol.user_id, "member")
    assert (await switch(carol, alice.org_id)).status_code == 200
    return World(alice, bob, carol)


async def _member_ids(actor: Actor) -> set[uuid.UUID]:
    response = await actor.client.get("/organizations/current/members")
    assert response.status_code == 200
    return {uuid.UUID(m["user_id"]) for m in response.json()}


# --- Visibility --------------------------------------------------------------------------------


async def test_each_tenant_sees_only_its_own_organization_and_members(world: World) -> None:
    acme = await world.alice.client.get("/organizations/current")
    globex = await world.bob.client.get("/organizations/current")

    assert acme.json()["name"] == "Acme"
    assert globex.json()["name"] == "Globex"
    assert await _member_ids(world.alice) == {world.alice.user_id, world.carol.user_id}
    assert await _member_ids(world.bob) == {world.bob.user_id}


async def test_me_lists_all_memberships_for_switching(world: World) -> None:
    me = (await world.carol.client.get("/auth/me")).json()

    assert me["active_organization"]["name"] == "Acme"
    assert me["role"] == "member"
    assert {(m["organization"]["name"], m["role"]) for m in me["memberships"]} == {
        ("Acme", "member"),
        ("Carol Co", "owner"),
    }


async def test_switching_organization(world: World) -> None:
    response = await switch(world.carol, world.carol.org_id)

    assert response.status_code == 200
    assert (await world.carol.client.get("/organizations/current")).json()["name"] == "Carol Co"


async def test_cannot_switch_into_an_organization_you_do_not_belong_to(world: World) -> None:
    response = await switch(world.alice, world.bob.org_id)

    assert response.status_code == 404  # same as a non-existent org: existence is not revealed
    assert (await world.alice.client.get("/organizations/current")).json()["name"] == "Acme"


async def test_cannot_manage_members_of_another_organization(world: World) -> None:
    """IDOR attempt: Alice targets Bob (a Globex member) by ID from inside Acme."""
    patch = await world.alice.client.patch(
        f"/organizations/current/members/{world.bob.user_id}", json={"role": "member"}
    )
    delete = await world.alice.client.delete(f"/organizations/current/members/{world.bob.user_id}")

    assert (patch.status_code, delete.status_code) == (404, 404)
    assert await _member_ids(world.bob) == {world.bob.user_id}


# --- Roles -------------------------------------------------------------------------------------


async def test_member_cannot_rename_organization_but_admin_can(
    world: World, owner_engine: AsyncEngine
) -> None:
    denied = await world.carol.client.patch("/organizations/current", json={"name": "Hacked"})
    assert denied.status_code == 403

    promoted = await world.alice.client.patch(
        f"/organizations/current/members/{world.carol.user_id}", json={"role": "admin"}
    )
    assert promoted.status_code == 204

    renamed = await world.carol.client.patch("/organizations/current", json={"name": "Acme Inc"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Acme Inc"


async def test_admin_cannot_grant_owner_role(world: World) -> None:
    await world.alice.client.patch(
        f"/organizations/current/members/{world.carol.user_id}", json={"role": "admin"}
    )

    response = await world.carol.client.patch(
        f"/organizations/current/members/{world.carol.user_id}", json={"role": "owner"}
    )

    assert response.status_code == 403


async def test_last_owner_cannot_demote_or_remove_themselves(world: World) -> None:
    demote = await world.alice.client.patch(
        f"/organizations/current/members/{world.alice.user_id}", json={"role": "admin"}
    )
    leave = await world.alice.client.delete(f"/organizations/current/members/{world.alice.user_id}")

    assert (demote.status_code, leave.status_code) == (409, 409)
    assert demote.json()["error"]["code"] == "last_owner"


async def test_owner_can_step_down_once_another_owner_exists(world: World) -> None:
    await world.alice.client.patch(
        f"/organizations/current/members/{world.carol.user_id}", json={"role": "owner"}
    )

    response = await world.alice.client.patch(
        f"/organizations/current/members/{world.alice.user_id}", json={"role": "member"}
    )

    assert response.status_code == 204


async def test_removed_member_loses_access_immediately(world: World) -> None:
    removed = await world.alice.client.delete(
        f"/organizations/current/members/{world.carol.user_id}"
    )
    assert removed.status_code == 204

    # Carol's session still points at Acme, but her access is gone on the very next request.
    response = await world.carol.client.get("/organizations/current")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "no_active_organization"
    me = (await world.carol.client.get("/auth/me")).json()
    assert me["active_organization"] is None
    assert [m["organization"]["name"] for m in me["memberships"]] == ["Carol Co"]


async def test_member_can_leave_an_organization(world: World) -> None:
    response = await world.carol.client.delete(
        f"/organizations/current/members/{world.carol.user_id}"
    )

    assert response.status_code == 204
    assert await _member_ids(world.alice) == {world.alice.user_id}
