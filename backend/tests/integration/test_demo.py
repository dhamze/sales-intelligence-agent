"""Sample data: loading fictional companies into an empty workspace, with and without AI content."""

import json
import re
from pathlib import Path
from typing import Any
from xml.sax.saxutils import unescape

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sia.ai.client import FakeLLMClient
from sia.modules.demo import ai_build, service
from sia.modules.demo.dataset import SAMPLE_COMPANIES
from sia.modules.enrichment.extraction import Evidence, ExtractedProfile, TextFact
from sia.modules.insights.providers import fake_brief
from tests.integration.conftest import ClientFactory
from tests.integration.helpers import Actor, add_member, make_actor, switch


@pytest.fixture
async def alice(make_client: ClientFactory) -> Actor:
    return await make_actor(make_client(), "alice@acme.example.com", "Acme")


@pytest.fixture
def no_ai_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(service, "SAMPLE_AI_PATH", tmp_path / "missing.json")


def quoting_profile(_system: str, content: str, _output_type: type[Any]) -> ExtractedProfile:
    """A fake profile whose description quotes the sample page itself (so it verifies)."""
    match = re.search(r'<page url="([^"]+)"[^>]*>\n(.*?)\.', content, re.DOTALL)
    assert match is not None
    url, first_sentence = match.group(1), unescape(match.group(2))
    return ExtractedProfile(
        description=TextFact(
            value=first_sentence + ".",
            evidence=[Evidence(source_url=url, quote=first_sentence)],
        ),
        industry=None,
        products=[],
        target_customers=[],
        business_model=None,
        headquarters_city=None,
        headquarters_country=None,
        employee_range=None,
        founded_year=None,
    )


@pytest.fixture
async def fake_ai_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data = await ai_build.build(FakeLLMClient(quoting_profile), FakeLLMClient(fake_brief))
    path = tmp_path / "sample_ai.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(service, "SAMPLE_AI_PATH", path)


async def test_loads_companies_contacts_icp_and_scores(
    alice: Actor, no_ai_content: None, owner_engine: AsyncEngine
) -> None:
    response = await alice.client.post("/sample-data")

    assert response.status_code == 201, response.text
    expected_contacts = sum(len(c.contacts) for c in SAMPLE_COMPANIES)
    assert response.json() == {
        "companies": len(SAMPLE_COMPANIES),
        "contacts": expected_contacts,
        "ai_profiles": 0,
        "briefs": 0,
    }
    icp = (await alice.client.get("/icp")).json()
    assert icp["status"] == {"total_companies": 12, "scored_current": 12}
    best = (await alice.client.get("/companies", params={"sort": "-icp_score"})).json()["items"]
    assert best[0]["icp_tier"] == "A"
    assert best[0]["attributes"] == {"Sample data": "Fictional company"}
    async with owner_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM ai_generations")) == 0  # no AI calls


async def test_only_empty_workspaces_and_admins(
    alice: Actor, no_ai_content: None, make_client: ClientFactory, owner_engine: AsyncEngine
) -> None:
    bob = await make_actor(make_client(), "bob@acme.example.com", "Bob's org")
    await add_member(owner_engine, alice.org_id, bob.user_id, "member")
    await switch(bob, alice.org_id)

    assert (await bob.client.post("/sample-data")).status_code == 403
    assert (await alice.client.post("/sample-data")).status_code == 201
    again = await alice.client.post("/sample-data")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "workspace_not_empty"


async def test_an_existing_icp_is_never_replaced(alice: Actor, no_ai_content: None) -> None:
    mine = {"criteria": [{"kind": "industry", "industries": ["Retail & E-commerce"]}]}
    await alice.client.put("/icp", json=mine)

    await alice.client.post("/sample-data")

    icp = (await alice.client.get("/icp")).json()
    assert icp["definition"]["criteria"][0]["industries"] == ["Retail & E-commerce"]
    assert icp["version"] == 1


async def test_pre_generated_ai_content_is_loaded_and_up_to_date(
    alice: Actor, fake_ai_content: None, owner_engine: AsyncEngine
) -> None:
    loaded = (await alice.client.post("/sample-data")).json()
    assert (loaded["ai_profiles"], loaded["briefs"]) == (12, 12)

    companies = (await alice.client.get("/companies", params={"limit": 100})).json()["items"]
    northwind = next(c for c in companies if c["name"] == "Northwind Ledger")
    assert northwind["description"]  # filled from the verified profile, like enrichment does

    result = (await alice.client.get(f"/companies/{northwind['id']}/brief")).json()
    brief = result["brief"]
    # The builder numbered the sources exactly like the app does: every citation still holds
    # against the sources as loaded (the loader re-checks them).
    assert brief["claims_dropped"] == 0
    assert brief["stale"] is False
    assert [s["id"] for s in brief["sources"]][:2] == ["W1", "W2"]
    profile = (await alice.client.get(f"/companies/{northwind['id']}/enrichment")).json()
    assert profile["profile"]["facts"]
    async with owner_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM ai_generations")) == 0
