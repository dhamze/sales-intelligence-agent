"""Contact CRUD through the API, including company links that must stay within one tenant."""

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from sia.core.tenancy import set_tenant_context
from tests.integration.conftest import ClientFactory
from tests.integration.helpers import Actor, make_actor


@pytest.fixture
async def alice(make_client: ClientFactory) -> Actor:
    return await make_actor(make_client(), "alice@acme.example.com", "Acme")


@pytest.fixture
async def bob(make_client: ClientFactory) -> Actor:
    return await make_actor(make_client(), "bob@globex.example.com", "Globex")


async def company(actor: Actor, name: str = "Initech", domain: str = "initech.com") -> str:
    response = await actor.client.post("/companies", json={"name": name, "domain": domain})
    assert response.status_code == 201
    company_id: str = response.json()["id"]
    return company_id


async def create(actor: Actor, **fields: Any) -> httpx.Response:
    return await actor.client.post("/contacts", json=fields)


async def test_create_contact_linked_to_company(alice: Actor) -> None:
    company_id = await company(alice)

    response = await create(
        alice,
        company_id=company_id,
        first_name="Peter",
        last_name="Gibbons",
        email="Peter.Gibbons@Initech.com",
        title="Software Engineer",
        phone="+1 (555) 010-0199",
        linkedin_url="linkedin.com/in/peter-gibbons",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["full_name"] == "Peter Gibbons"  # computed by the database
    assert body["email"] == "peter.gibbons@initech.com"
    assert body["linkedin_url"] == "https://linkedin.com/in/peter-gibbons"
    assert body["company_id"] == company_id


@pytest.mark.parametrize(
    "fields",
    [
        {},  # neither email nor name
        {"title": "CEO"},
        {"email": "not-an-email"},
        {"first_name": "A", "phone": "call me maybe"},
        {"first_name": "A", "linkedin_url": "javascript:alert(1)"},
    ],
)
async def test_invalid_contact_input_is_rejected(alice: Actor, fields: dict[str, Any]) -> None:
    assert (await create(alice, **fields)).status_code == 422


async def test_duplicate_email_is_rejected(alice: Actor) -> None:
    first = (await create(alice, email="peter@initech.com")).json()

    duplicate = await create(alice, email="PETER@initech.com", first_name="Pete")

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["details"] == [{"existing_contact_id": first["id"]}]


async def test_cannot_link_to_another_tenants_company(alice: Actor, bob: Actor) -> None:
    bobs_company = await company(bob, "Globex", "globex.com")

    response = await create(alice, first_name="Spy", company_id=bobs_company)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "company_not_found"


async def test_composite_foreign_key_blocks_cross_tenant_link_in_the_database(
    alice: Actor, bob: Actor, engine: AsyncEngine
) -> None:
    """Even bypassing the API's checks: FK checks ignore RLS, so only the composite foreign key
    stops a contact in Acme from pointing at Globex's company."""
    bobs_company = uuid.UUID(await company(bob, "Globex", "globex.com"))

    with pytest.raises(DBAPIError, match="fk_contacts_company_same_org"):
        async with engine.begin() as conn:
            await set_tenant_context(conn, user_id=alice.user_id, organization_id=alice.org_id)
            await conn.execute(
                text(
                    "INSERT INTO contacts (organization_id, company_id, first_name, source) "
                    "VALUES (:org, :company, 'Spy', 'manual')"
                ),
                {"org": alice.org_id, "company": bobs_company},
            )


async def test_patch_cannot_leave_contact_without_email_or_name(alice: Actor) -> None:
    contact = (await create(alice, email="peter@initech.com")).json()

    response = await alice.client.patch(f"/contacts/{contact['id']}", json={"email": None})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "contact_needs_email_or_name"


async def test_deleting_company_keeps_its_contacts_unlinked(alice: Actor) -> None:
    company_id = await company(alice)
    contact = (await create(alice, first_name="Peter", company_id=company_id)).json()

    assert (await alice.client.delete(f"/companies/{company_id}")).status_code == 204

    after = (await alice.client.get(f"/contacts/{contact['id']}")).json()
    assert after["company_id"] is None
    assert after["full_name"] == "Peter"


async def test_list_contacts_of_one_company(alice: Actor) -> None:
    initech = await company(alice)
    hooli = await company(alice, "Hooli", "hooli.com")
    await create(alice, first_name="Peter", company_id=initech)
    await create(alice, first_name="Gavin", company_id=hooli)

    response = await alice.client.get("/contacts", params={"company_id": initech})

    assert [c["full_name"] for c in response.json()["items"]] == ["Peter"]


async def test_other_tenants_cannot_access_contacts(alice: Actor, bob: Actor) -> None:
    contact = (await create(alice, email="peter@initech.com")).json()
    url = f"/contacts/{contact['id']}"

    assert (await bob.client.get(url)).status_code == 404
    assert (await bob.client.patch(url, json={"title": "x"})).status_code == 404
    assert (await bob.client.delete(url)).status_code == 404
    assert (await bob.client.get("/contacts")).json()["items"] == []
