"""ICP scoring against the real database: API, rescoring triggers, the background job, RLS."""

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import procrastinate
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sia.ai.client import FakeLLMClient
from sia.core.config import Settings
from sia.modules.enrichment import service as enrichment
from sia.modules.enrichment.providers import FakeSiteReader, fake_profile
from sia.modules.scoring import service
from sia.worker import configured_app, runtime
from tests.integration.conftest import ClientFactory
from tests.integration.helpers import Actor, add_member, make_actor, switch

ICP = {
    "criteria": [
        {"kind": "industry", "industries": ["Software", "Fintech"], "importance": 5},
        {"kind": "size", "min_employees": 50, "max_employees": 500, "importance": 3},
        {"kind": "country", "countries": ["DE"], "importance": 2},
    ]
}


@pytest.fixture
async def alice(make_client: ClientFactory) -> Actor:
    return await make_actor(make_client(), "alice@acme.example.com", "Acme")


@pytest.fixture
async def worker(test_settings: Settings) -> AsyncIterator[procrastinate.App]:
    runtime.init(test_settings)
    configured = configured_app(test_settings)
    async with configured.open_async():
        yield configured
    await runtime.dispose()


async def run_jobs(worker: procrastinate.App) -> None:
    await worker.run_worker_async(
        queues=[service.QUEUE], wait=False, install_signal_handlers=False, listen_notify=False
    )


async def new_company(actor: Actor, name: str, **fields: Any) -> str:
    response = await actor.client.post("/companies", json={"name": name, **fields})
    assert response.status_code == 201, response.text
    company_id: str = response.json()["id"]
    return company_id


async def company(actor: Actor, company_id: str) -> dict[str, Any]:
    body: dict[str, Any] = (await actor.client.get(f"/companies/{company_id}")).json()
    return body


async def save_icp(actor: Actor, icp: dict[str, Any] = ICP) -> dict[str, Any]:
    response = await actor.client.put("/icp", json=icp)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def pending_jobs(owner_engine: AsyncEngine) -> int:
    async with owner_engine.connect() as conn:
        count = await conn.scalar(
            text(
                "SELECT count(*) FROM procrastinate_jobs WHERE task_name = :t AND status = 'todo'"
            ),
            {"t": service.TASK_NAME},
        )
    return int(count or 0)


# --- Without an ICP ---------------------------------------------------------------------------


async def test_without_an_icp_nothing_is_scored(alice: Actor, owner_engine: AsyncEngine) -> None:
    company_id = await new_company(alice, "Initech", industry="Software")

    assert (await alice.client.get("/icp")).json() is None
    assert (await alice.client.get(f"/companies/{company_id}/score")).json() is None
    body = await company(alice, company_id)
    assert (body["icp_score"], body["icp_tier"]) == (None, None)
    assert await pending_jobs(owner_engine) == 0


# --- Saving the ICP and the full rescore ------------------------------------------------------


async def test_saving_the_icp_rescores_everything_in_the_background(
    alice: Actor, owner_engine: AsyncEngine, worker: procrastinate.App
) -> None:
    perfect = await new_company(
        alice, "Perfect", industry="Software", employee_count=100, country="Germany"
    )
    partial = await new_company(alice, "Partial", industry="Fintech", employee_count=5)
    unknown = await new_company(alice, "Unknown")
    before = await company(alice, perfect)

    saved = await save_icp(alice)

    assert saved["version"] == 1
    assert saved["status"] == {"total_companies": 3, "scored_current": 0}
    assert await pending_jobs(owner_engine) == 1
    await save_icp(alice)  # a second save while the job waits: still one job
    assert await pending_jobs(owner_engine) == 1

    await run_jobs(worker)

    status = (await alice.client.get("/icp")).json()["status"]
    assert status == {"total_companies": 3, "scored_current": 3}
    scores = {cid: (await company(alice, cid))["icp_score"] for cid in (perfect, partial, unknown)}
    assert scores == {perfect: 100, partial: 50, unknown: 0}
    after = await company(alice, perfect)
    assert after["icp_tier"] == "A"
    assert after["updated_at"] == before["updated_at"]  # a score is not an edit

    detail = (await alice.client.get(f"/companies/{partial}/score")).json()
    assert detail["current"] is True
    assert detail["tier"] == "B"
    assert [c["status"] for c in detail["breakdown"]] == ["match", "miss", "unknown"]
    assert detail["breakdown"][2]["detail"] == "Country unknown (enrich to fill in)"


async def test_changing_the_icp_marks_old_scores_until_rescored(
    alice: Actor, worker: procrastinate.App
) -> None:
    company_id = await new_company(alice, "Initech", industry="Software")
    await save_icp(alice)
    await run_jobs(worker)

    changed = await save_icp(
        alice, {"criteria": [{"kind": "industry", "industries": ["Retail"], "importance": 1}]}
    )
    assert changed["version"] == 2
    stale = (await alice.client.get(f"/companies/{company_id}/score")).json()
    assert (stale["current"], stale["icp_version"]) == (False, 1)

    await run_jobs(worker)
    fresh = (await alice.client.get(f"/companies/{company_id}/score")).json()
    assert (fresh["current"], fresh["score"]) == (True, 0)


# --- Single-company changes are rescored immediately ------------------------------------------


async def test_new_and_edited_companies_are_scored_immediately(alice: Actor) -> None:
    await save_icp(alice)  # no companies yet, nothing to wait for

    company_id = await new_company(alice, "Initech", industry="Software", country="DE")
    assert (await company(alice, company_id))["icp_score"] == 70

    response = await alice.client.patch(f"/companies/{company_id}", json={"employee_count": 120})
    assert response.json()["icp_score"] == 100
    assert response.json()["icp_tier"] == "A"


async def test_contacts_change_the_score_immediately(alice: Actor) -> None:
    await save_icp(
        alice, {"criteria": [{"kind": "has_contacts", "min_contacts": 1, "importance": 3}]}
    )
    first = await new_company(alice, "First")
    second = await new_company(alice, "Second")
    assert (await company(alice, first))["icp_score"] == 0

    contact = (
        await alice.client.post("/contacts", json={"email": "a@first.com", "company_id": first})
    ).json()
    assert (await company(alice, first))["icp_score"] == 100

    # Moving the contact rescores both the old and the new company.
    await alice.client.patch(f"/contacts/{contact['id']}", json={"company_id": second})
    assert (await company(alice, first))["icp_score"] == 0
    assert (await company(alice, second))["icp_score"] == 100

    await alice.client.delete(f"/contacts/{contact['id']}")
    assert (await company(alice, second))["icp_score"] == 0


async def test_enrichment_rescores_with_verified_facts(
    alice: Actor, worker: procrastinate.App
) -> None:
    await save_icp(alice)
    company_id = await new_company(alice, "Initech", domain="initech.com")
    assert (await company(alice, company_id))["icp_score"] == 0
    run = (await alice.client.post(f"/companies/{company_id}/enrich")).json()

    await enrichment.run_enrichment(
        organization_id=alice.org_id,
        company_id=uuid.UUID(company_id),
        run_id=uuid.UUID(run["id"]),
        reader=FakeSiteReader(),
        llm=FakeLLMClient(fake_profile),
    )

    # The fake profile says Fintech, Germany: industry (50) + country "DE" (20) of 100.
    detail = (await alice.client.get(f"/companies/{company_id}/score")).json()
    assert detail["score"] == 70
    assert detail["breakdown"][2]["status"] == "match"


async def test_an_import_queues_a_rescore_only_when_an_icp_exists(
    alice: Actor, owner_engine: AsyncEngine
) -> None:
    async def import_csv(csv: str) -> None:
        upload = await alice.client.post(
            "/imports",
            data={"entity_type": "companies"},
            files={"file": ("c.csv", csv.encode(), "text/csv")},
        )
        assert upload.status_code == 201, upload.text
        done = await alice.client.post(f"/imports/{upload.json()['id']}/commit", json={})
        assert done.status_code == 200, done.text

    await import_csv("name,domain\nA,a.com\n")
    assert await pending_jobs(owner_engine) == 0

    await save_icp(alice)
    async with owner_engine.begin() as conn:  # pretend the save's job already ran
        await conn.execute(text("DELETE FROM procrastinate_jobs"))
    await import_csv("name,domain\nB,b.com\n")
    assert await pending_jobs(owner_engine) == 1


# --- Listing by score -------------------------------------------------------------------------


async def test_list_sorts_by_score_across_pages_and_filters_by_tier(
    alice: Actor, owner_engine: AsyncEngine
) -> None:
    await save_icp(alice, {"criteria": [{"kind": "size", "min_employees": 0, "importance": 1}]})
    # Scores come from the size criterion only: known size = 100, unknown = 0.
    for i in range(30):
        await new_company(alice, f"Sized {i:02}", employee_count=i)
    for i in range(10):
        await new_company(alice, f"Unsized {i:02}")
    async with owner_engine.begin() as conn:  # a few companies not scored yet (e.g. mid-import)
        await conn.execute(
            text(
                "UPDATE companies SET icp_score = NULL "
                "WHERE name IN ('Unsized 00', 'Unsized 01', 'Unsized 02')"
            )
        )

    seen: list[dict[str, Any]] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"sort": "-icp_score", "limit": 7}
        if cursor:
            params["cursor"] = cursor
        page = (await alice.client.get("/companies", params=params)).json()
        seen += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            break

    assert len(seen) == 40
    assert len({c["id"] for c in seen}) == 40
    scores = [c["icp_score"] for c in seen]
    assert scores == [100] * 30 + [0] * 7 + [None] * 3  # unscored last

    tier_a = (await alice.client.get("/companies", params={"tier": "A", "limit": 100})).json()
    assert len(tier_a["items"]) == 30
    c_or_d = (
        await alice.client.get("/companies", params={"tier": ["C", "D"], "limit": 100})
    ).json()
    assert len(c_or_d["items"]) == 7  # unscored companies have no tier


# --- Preview ----------------------------------------------------------------------------------


async def test_preview_rates_companies_without_storing_anything(alice: Actor) -> None:
    for i in range(12):
        await new_company(alice, f"Software {i:02}", industry="Software")
    await new_company(alice, "Retailer", industry="Retail")

    response = await alice.client.post(
        "/icp/preview", json={"criteria": [{"kind": "industry", "industries": ["Software"]}]}
    )

    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["total_companies"] == 13
    assert preview["tiers"] == {"A": 12, "B": 0, "C": 0, "D": 1}
    assert [c["name"] for c in preview["top"]] == [f"Software {i:02}" for i in range(10)]
    assert preview["average_completeness"] == 1.0
    assert (await alice.client.get("/icp")).json() is None


# --- Permissions, validation, deletion, isolation ---------------------------------------------


async def test_only_admins_change_the_icp(
    alice: Actor, make_client: ClientFactory, owner_engine: AsyncEngine
) -> None:
    bob = await make_actor(make_client(), "bob@acme.example.com", "Bob's own org")
    await add_member(owner_engine, alice.org_id, bob.user_id, "member")
    await switch(bob, alice.org_id)

    for method, path in [("PUT", "/icp"), ("POST", "/icp/preview"), ("DELETE", "/icp")]:
        response = await bob.client.request(method, path, json=ICP)
        assert response.status_code == 403, (method, path)
    assert (await bob.client.post("/icp/rescore")).status_code == 403
    await save_icp(alice)
    assert (await bob.client.get("/icp")).json()["version"] == 1  # members can read it


async def test_invalid_icp_is_rejected(alice: Actor) -> None:
    bad = {"criteria": [{"kind": "size", "min_employees": 500, "max_employees": 50}]}
    response = await alice.client.put("/icp", json=bad)
    assert response.status_code == 422
    assert "minimum is larger" in response.text


async def test_rescore_without_an_icp_is_not_found(alice: Actor) -> None:
    assert (await alice.client.post("/icp/rescore")).status_code == 404


async def test_deleting_the_icp_removes_every_score(
    alice: Actor, owner_engine: AsyncEngine
) -> None:
    await save_icp(alice)
    company_id = await new_company(alice, "Initech", industry="Software")
    assert (await company(alice, company_id))["icp_score"] is not None

    assert (await alice.client.delete("/icp")).status_code == 204

    assert (await alice.client.get("/icp")).json() is None
    assert (await company(alice, company_id))["icp_score"] is None
    async with owner_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM company_scores")) == 0


async def test_scores_are_invisible_to_other_tenants(
    alice: Actor, make_client: ClientFactory
) -> None:
    await save_icp(alice)
    company_id = await new_company(alice, "Initech", industry="Software")
    mallory = await make_actor(make_client(), "mallory@evil.example.com", "Evil")

    assert (await mallory.client.get(f"/companies/{company_id}/score")).status_code == 404
    assert (await mallory.client.get("/icp")).json() is None
    preview = (await mallory.client.post("/icp/preview", json=ICP)).json()
    assert preview["total_companies"] == 0


# --- Scale ------------------------------------------------------------------------------------


async def test_rescoring_50k_companies_is_fast_enough(
    alice: Actor, owner_engine: AsyncEngine, worker: procrastinate.App
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO companies (organization_id, name, domain, industry, employee_count,"
                " country, source) "
                "SELECT :org, 'Company ' || i, 'c' || i || '.example', "
                "(ARRAY['Software','Retail','Fintech'])[1 + i % 3], i % 1000, "
                "(ARRAY['DE','US'])[1 + i % 2], 'import' "
                "FROM generate_series(1, 50000) AS i"
            ),
            {"org": alice.org_id},
        )
    await save_icp(alice)
    started = time.perf_counter()
    async with runtime.tenant_session(organization_id=alice.org_id) as db:
        scored = await service.rescore_organization(db, alice.org_id)
    elapsed = time.perf_counter() - started

    assert scored == 50_000
    print(f"\nRescoring 50,000 companies: {elapsed:.2f}s")
    assert elapsed < 60, f"rescoring 50k companies took {elapsed:.1f}s"

    started = time.perf_counter()
    page = await alice.client.get("/companies", params={"sort": "-icp_score", "tier": "A"})
    list_ms = (time.perf_counter() - started) * 1000
    assert page.status_code == 200
    assert all(c["icp_tier"] == "A" for c in page.json()["items"])
    print(f"First page sorted by score, tier A: {list_ms:.0f} ms (through the API)")

    started = time.perf_counter()
    preview = await alice.client.post("/icp/preview", json=ICP)
    preview_s = time.perf_counter() - started
    assert preview.json()["total_companies"] == 50_000
    print(f"Preview over 50,000 companies: {preview_s:.2f}s")
    assert preview_s < 20, f"preview over 50k companies took {preview_s:.1f}s"
