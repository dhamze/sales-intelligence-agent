"""Company CRUD through the API, including duplicate detection and tenant isolation."""

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import ClientFactory
from tests.integration.helpers import Actor, add_member, make_actor, switch


@pytest.fixture
async def alice(make_client: ClientFactory) -> Actor:
    return await make_actor(make_client(), "alice@acme.example.com", "Acme")


@pytest.fixture
async def bob(make_client: ClientFactory) -> Actor:
    return await make_actor(make_client(), "bob@globex.example.com", "Globex")


async def create(actor: Actor, **fields: Any) -> httpx.Response:
    return await actor.client.post("/companies", json={"name": "Initech", **fields})


async def test_create_company(alice: Actor) -> None:
    response = await create(
        alice,
        name="Initech",
        website="https://www.initech.com/about",
        industry="Software",
        employee_count=250,
        attributes={"crm_id": "0012", "tier": 1},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["domain"] == "initech.com"  # derived from the website
    assert body["website"] == "https://www.initech.com/about"
    assert body["source"] == "manual"
    assert body["attributes"] == {"crm_id": "0012", "tier": 1}
    fetched = await alice.client.get(f"/companies/{body['id']}")
    assert fetched.json() == body


async def test_blank_strings_are_stored_as_null(alice: Actor) -> None:
    body = (await create(alice, industry="  ", city="", domain="")).json()

    assert (body["industry"], body["city"], body["domain"]) == (None, None, None)


@pytest.mark.parametrize("variant", ["INITECH.com", "https://www.initech.com", "shop.initech.com"])
async def test_same_domain_in_any_form_is_a_duplicate(alice: Actor, variant: str) -> None:
    first = (await create(alice, domain="initech.com")).json()

    duplicate = await create(alice, name="Initech Ltd", domain=variant)

    assert duplicate.status_code == 409
    error = duplicate.json()["error"]
    assert error["code"] == "domain_taken"
    assert error["details"] == [{"existing_company_id": first["id"]}]


async def test_same_domain_is_allowed_in_another_organization(alice: Actor, bob: Actor) -> None:
    assert (await create(alice, domain="initech.com")).status_code == 201
    assert (await create(bob, domain="initech.com")).status_code == 201


@pytest.mark.parametrize(
    "fields",
    [
        {"name": ""},
        {"domain": "localhost"},
        {"domain": "10.0.0.1"},
        {"website": "javascript:alert(1)"},
        {"employee_count": -1},
        {"attributes": {f"k{i}": i for i in range(101)}},
        {"attributes": {"nested": {"not": "allowed"}}},
        {"organization_id": "00000000-0000-0000-0000-000000000000"},  # cannot choose tenant
    ],
)
async def test_invalid_company_input_is_rejected(alice: Actor, fields: dict[str, Any]) -> None:
    assert (await create(alice, **fields)).status_code == 422


async def test_patch_updates_only_given_fields_and_null_clears(alice: Actor) -> None:
    company = (await create(alice, industry="Software", city="Austin")).json()

    response = await alice.client.patch(
        f"/companies/{company['id']}", json={"city": None, "employee_count": 300}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["industry"], body["city"], body["employee_count"]) == ("Software", None, 300)
    assert body["updated_at"] > company["updated_at"]


async def test_patch_cannot_clear_name_or_take_existing_domain(alice: Actor) -> None:
    await create(alice, name="Hooli", domain="hooli.com")
    company = (await create(alice, domain="initech.com")).json()

    no_name = await alice.client.patch(f"/companies/{company['id']}", json={"name": None})
    taken = await alice.client.patch(f"/companies/{company['id']}", json={"domain": "hooli.com"})

    assert no_name.status_code == 422
    assert taken.status_code == 409


async def test_delete_requires_admin(
    alice: Actor, make_client: ClientFactory, owner_engine: AsyncEngine
) -> None:
    company = (await create(alice)).json()
    carol = await make_actor(make_client(), "carol@example.com", "Carol Co")
    await add_member(owner_engine, alice.org_id, carol.user_id, "member")
    await switch(carol, alice.org_id)

    assert (await carol.client.delete(f"/companies/{company['id']}")).status_code == 403
    assert (await alice.client.delete(f"/companies/{company['id']}")).status_code == 204
    assert (await alice.client.get(f"/companies/{company['id']}")).status_code == 404


async def test_other_tenants_cannot_read_change_or_delete(alice: Actor, bob: Actor) -> None:
    company = (await create(alice)).json()
    url = f"/companies/{company['id']}"

    assert (await bob.client.get(url)).status_code == 404
    assert (await bob.client.patch(url, json={"name": "Pwned"})).status_code == 404
    assert (await bob.client.delete(url)).status_code == 404
    assert (await bob.client.get("/companies")).json()["items"] == []
    assert (await alice.client.get(url)).json()["name"] == "Initech"


async def test_requires_login_and_active_organization(client: httpx.AsyncClient) -> None:
    assert (await client.get("/companies")).status_code == 401
    assert (await client.post("/companies", json={"name": "X"})).status_code == 401
