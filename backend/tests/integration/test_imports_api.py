"""CSV import end to end: upload -> preview -> commit, merge rules, limits, tenant isolation."""

import time
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import ClientFactory
from tests.integration.helpers import Actor, make_actor


@pytest.fixture
async def alice(make_client: ClientFactory) -> Actor:
    return await make_actor(make_client(), "alice@acme.example.com", "Acme")


async def upload(
    actor: Actor, csv: str | bytes, entity: str = "companies", filename: str = "list.csv"
) -> httpx.Response:
    content = csv.encode() if isinstance(csv, str) else csv
    return await actor.client.post(
        "/imports",
        files={"file": (filename, content, "text/csv")},
        data={"entity_type": entity},
    )


async def commit(actor: Actor, import_id: str, **body: Any) -> httpx.Response:
    return await actor.client.post(f"/imports/{import_id}/commit", json=body)


async def run_import(actor: Actor, csv: str, entity: str = "companies") -> dict[str, Any]:
    preview = await upload(actor, csv, entity)
    assert preview.status_code == 201, preview.text
    result = await commit(actor, preview.json()["id"])
    assert result.status_code == 200, result.text
    body: dict[str, Any] = result.json()
    return body


async def companies_by_domain(actor: Actor) -> dict[str, dict[str, Any]]:
    items = (await actor.client.get("/companies", params={"limit": 100})).json()["items"]
    return {c["domain"]: c for c in items}


COMPANIES_CSV = (
    "Company Name,Website,Industry,Employees,CRM ID\n"
    'Acme,https://www.acme.com,Software,"1,200",A-1\n'
    "Globex,globex.com,Energy,300,G-7\n"
    "Bad Row,localhost,,,\n"
    "Acme Duplicate,acme.com,,,\n"
)


async def test_preview_reports_what_will_happen_and_writes_nothing(alice: Actor) -> None:
    response = await upload(alice, COMPANIES_CSV)

    assert response.status_code == 201
    preview = response.json()
    assert preview["status"] == "preview"
    assert preview["mapping"] == {
        "Company Name": "name",
        "Website": "website",
        "Industry": "industry",
        "Employees": "employee_count",
        "CRM ID": "attributes",
    }
    assert (preview["row_count"], preview["valid_count"]) == (4, 2)
    assert (preview["invalid_count"], preview["duplicate_count"]) == (1, 1)
    assert {(e["row"], e["field"]) for e in preview["errors"]} == {(4, "website"), (5, "domain")}
    assert preview["sample_rows"][0]["Company Name"] == "Acme"
    assert (await alice.client.get("/companies")).json()["items"] == []  # nothing written yet


async def test_commit_creates_companies(alice: Actor) -> None:
    result = await run_import(alice, COMPANIES_CSV)

    assert result["status"] == "completed"
    assert (result["created_count"], result["updated_count"]) == (2, 0)
    companies = await companies_by_domain(alice)
    assert set(companies) == {"acme.com", "globex.com"}
    acme = companies["acme.com"]
    assert (acme["employee_count"], acme["source"]) == (1200, "import")
    assert acme["attributes"] == {"CRM ID": "A-1"}


async def test_import_fills_empty_fields_but_never_overwrites(alice: Actor) -> None:
    created = await alice.client.post(
        "/companies",
        json={"name": "Acme (curated)", "domain": "acme.com", "industry": "Robotics"},
    )
    assert created.status_code == 201

    result = await run_import(
        alice, "Name,Domain,Industry,City,Tier\nAcme Corp,acme.com,Software,Berlin,Gold\n"
    )

    assert (result["created_count"], result["updated_count"]) == (0, 1)
    acme = (await companies_by_domain(alice))["acme.com"]
    assert acme["name"] == "Acme (curated)"  # existing value kept
    assert acme["industry"] == "Robotics"  # existing value kept
    assert acme["city"] == "Berlin"  # empty field filled
    assert acme["attributes"] == {"Tier": "Gold"}
    assert acme["source"] == "manual"


async def test_reimporting_the_same_file_changes_nothing(alice: Actor) -> None:
    await run_import(alice, COMPANIES_CSV)

    again = await run_import(alice, COMPANIES_CSV)

    assert (again["created_count"], again["updated_count"], again["unchanged_count"]) == (0, 0, 2)


async def test_contacts_import_links_companies_by_domain(alice: Actor) -> None:
    await run_import(alice, "Name,Domain\nInitech,initech.com\n")

    result = await run_import(
        alice,
        "Full Name,Email,Title\n"
        "Peter Gibbons,peter@initech.com,Engineer\n"
        "Bob Slydell,bob@gmail.com,Consultant\n"
        "Nobody,,\n",
        entity="contacts",
    )

    assert result["created_count"] == 3
    contacts = (await alice.client.get("/contacts", params={"sort": "full_name"})).json()["items"]
    linked = {c["full_name"]: c["company_id"] is not None for c in contacts}
    assert linked == {"Bob Slydell": False, "Nobody": False, "Peter Gibbons": True}


async def test_mapping_can_be_corrected_at_commit(alice: Actor) -> None:
    preview = (await upload(alice, "Org,Site\nAcme,acme.com\n")).json()
    assert preview["mapping"] == {"Org": "attributes", "Site": "website"}  # "Org" not recognised

    result = await commit(alice, preview["id"], mapping={"Org": "name", "Site": "website"})

    assert result.status_code == 200
    assert (await companies_by_domain(alice))["acme.com"]["name"] == "Acme"


async def test_invalid_mapping_is_rejected(alice: Actor) -> None:
    preview = (await upload(alice, "Org,Site\nAcme,acme.com\n")).json()

    response = await commit(alice, preview["id"], mapping={"Org": "name", "Site": "name"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_mapping"


async def test_import_commits_once_and_then_deletes_the_file(
    alice: Actor, owner_engine: AsyncEngine
) -> None:
    preview = (await upload(alice, COMPANIES_CSV)).json()
    assert (await commit(alice, preview["id"])).status_code == 200

    second = await commit(alice, preview["id"])

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "import_not_pending"
    async with owner_engine.connect() as conn:
        stored = await conn.scalar(
            text("SELECT file_content FROM imports WHERE id = :id"), {"id": preview["id"]}
        )
    assert stored is None  # data minimisation: the uploaded file is not kept


async def test_expired_preview_cannot_be_committed(alice: Actor, owner_engine: AsyncEngine) -> None:
    preview = (await upload(alice, COMPANIES_CSV)).json()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE imports SET created_at = now() - interval '25 hours' WHERE id = :id"),
            {"id": preview["id"]},
        )

    response = await commit(alice, preview["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "import_expired"


@pytest.mark.parametrize(
    ("content", "status", "code"),
    [
        (b"", 422, "invalid_import_file"),
        (b"\x89PNG\r\n\x1a\n\x00\x00binary", 422, "invalid_import_file"),
        (b"Name\n" + b"x" * (5 * 1024 * 1024), 413, "payload_too_large"),  # > 5 MB route limit
        (b"Name\n" + b"x" * (7 * 1024 * 1024), 413, "payload_too_large"),  # > 6 MB body limit
    ],
)
async def test_unusable_uploads_are_rejected(
    alice: Actor, content: bytes, status: int, code: str
) -> None:
    response = await upload(alice, content)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_wrong_entity_type_is_rejected(alice: Actor) -> None:
    assert (await upload(alice, COMPANIES_CSV, entity="users")).status_code == 422


async def test_other_tenants_cannot_see_or_commit_an_import(
    alice: Actor, make_client: ClientFactory
) -> None:
    bob = await make_actor(make_client(), "bob@globex.example.com", "Globex")
    preview = (await upload(alice, COMPANIES_CSV)).json()

    assert (await bob.client.get(f"/imports/{preview['id']}")).status_code == 404
    assert (await commit(bob, preview["id"])).status_code == 404
    assert (await bob.client.get("/imports")).json()["items"] == []
    assert (await commit(bob, str(uuid.uuid4()))).status_code == 404


async def test_imports_are_listed_newest_first(alice: Actor) -> None:
    first = (await upload(alice, COMPANIES_CSV, filename="first.csv")).json()
    second = (await upload(alice, COMPANIES_CSV, filename="second.csv")).json()

    listed = (await alice.client.get("/imports")).json()["items"]

    assert [i["id"] for i in listed] == [second["id"], first["id"]]


async def test_maximum_size_import_completes(alice: Actor) -> None:
    rows = "\n".join(f"Company {i},company{i}.com,Software,{i % 500}" for i in range(10_000))
    csv = "Name,Website,Industry,Employees\n" + rows + "\n"

    started = time.perf_counter()
    result = await run_import(alice, csv)
    elapsed = time.perf_counter() - started

    assert result["created_count"] == 10_000
    assert elapsed < 30, f"10,000-row import took {elapsed:.1f}s"
    print(f"\n10,000-row import (preview + commit): {elapsed:.2f}s")
