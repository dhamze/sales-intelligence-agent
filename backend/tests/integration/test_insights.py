"""Account briefs end to end against the real database (fake AI, never the network)."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sia.ai.client import FakeLLMClient
from sia.core.config import Settings
from sia.main import create_app
from sia.modules.enrichment import service as enrichment
from sia.modules.enrichment.providers import FakeSiteReader, fake_profile
from sia.modules.insights import service
from sia.modules.insights.briefs import BriefOutput, Citation, Claim
from sia.modules.insights.providers import fake_brief
from sia.worker import runtime
from tests.integration.conftest import ClientFactory
from tests.integration.helpers import Actor, make_actor


@pytest.fixture
async def worker_runtime(test_settings: Settings) -> AsyncIterator[None]:
    runtime.init(test_settings)
    yield
    await runtime.dispose()


@pytest.fixture
async def alice(make_client: ClientFactory) -> Actor:
    return await make_actor(make_client(), "alice@acme.example.com", "Acme")


@asynccontextmanager
async def client_for(app: FastAPI, actor: Actor) -> AsyncIterator[httpx.AsyncClient]:
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        client.cookies.update(actor.client.cookies)
        yield client


async def new_company(actor: Actor, **fields: Any) -> str:
    response = await actor.client.post(
        "/companies", json={"name": "Initech", "domain": "initech.com", **fields}
    )
    assert response.status_code == 201, response.text
    company_id: str = response.json()["id"]
    return company_id


async def request_brief(actor: Actor, company_id: str) -> dict[str, Any]:
    response = await actor.client.post(f"/companies/{company_id}/brief")
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


async def run(actor: Actor, queued: dict[str, Any], llm: Any = None) -> Any:
    llm = llm or FakeLLMClient(fake_brief)
    await service.run_brief(
        organization_id=actor.org_id,
        company_id=uuid.UUID(queued["company_id"]),
        run_id=uuid.UUID(queued["id"]),
        llm=llm,
    )
    return llm


async def get_brief(actor: Actor, company_id: str) -> dict[str, Any]:
    response = await actor.client.get(f"/companies/{company_id}/brief")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def enrich(actor: Actor, company_id: str) -> None:
    queued = (await actor.client.post(f"/companies/{company_id}/enrich")).json()
    await enrichment.run_enrichment(
        organization_id=actor.org_id,
        company_id=uuid.UUID(company_id),
        run_id=uuid.UUID(queued["id"]),
        reader=FakeSiteReader(),
        llm=FakeLLMClient(fake_profile),
    )


async def test_request_creates_one_run_and_one_job(alice: Actor, owner_engine: AsyncEngine) -> None:
    company_id = await new_company(alice)

    first = await request_brief(alice, company_id)
    again = await request_brief(alice, company_id)  # still queued: same run

    assert first["status"] == "queued"
    assert again["id"] == first["id"]
    async with owner_engine.connect() as conn:
        jobs = (
            await conn.execute(
                text("SELECT args FROM procrastinate_jobs WHERE task_name = :t"),
                {"t": service.TASK_NAME},
            )
        ).scalars()
        assert [j["run_id"] for j in jobs] == [first["id"]]


async def test_brief_is_written_from_verified_sources_and_logged(
    alice: Actor, worker_runtime: None, owner_engine: AsyncEngine
) -> None:
    company_id = await new_company(alice, industry="Software")
    await enrich(alice, company_id)
    await alice.client.post(
        "/contacts",
        json={
            "first_name": "Dana",
            "last_name": "Secret",
            "email": "dana.secret@initech.com",
            "title": "VP Finance",
            "company_id": company_id,
        },
    )

    llm = await run(alice, await request_brief(alice, company_id))

    result = await get_brief(alice, company_id)
    assert result["latest_run"]["status"] == "succeeded"
    brief = result["brief"]
    assert brief["claims_dropped"] == 0
    assert brief["stale"] is False
    assert brief["summary"][0]["citations"][0]["source_id"] == "W1"
    assert brief["outreach"]["discovery_questions"]
    assert [s["id"] for s in brief["sources"]] == ["W1", "R", "C"]
    assert brief["sources"][0]["url"] == "https://initech.com/"
    assert "text" not in brief["sources"][0]  # page text stays on the server

    # Contacts are shared with the model by job title only (decision 2026-11-04).
    _, prompt = llm.calls[0]
    assert "VP Finance" in prompt
    assert "Dana" not in prompt
    assert "Secret" not in prompt
    assert "dana.secret" not in prompt

    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT purpose, prompt_version, outcome FROM ai_generations "
                    "WHERE purpose = 'account_brief'"
                )
            )
        ).one()
    assert tuple(row) == ("account_brief", "account-brief-v1", "success")


async def test_brief_goes_out_of_date_when_the_company_changes(
    alice: Actor, worker_runtime: None
) -> None:
    company_id = await new_company(alice)
    await run(alice, await request_brief(alice, company_id))
    assert (await get_brief(alice, company_id))["brief"]["stale"] is False

    await alice.client.patch(f"/companies/{company_id}", json={"employee_count": 300})

    assert (await get_brief(alice, company_id))["brief"]["stale"] is True


async def test_unsupported_claims_are_dropped_and_counted(
    alice: Actor, worker_runtime: None
) -> None:
    def inventive(_s: str, _c: str, _t: type[Any]) -> BriefOutput:
        return BriefOutput(
            summary=[
                Claim(
                    text="Initech is a company.",
                    citations=[Citation(source_id="R", quote="Company name: Initech")],
                )
            ],
            fit=[],
            key_facts=[
                Claim(
                    text="Initech raised $50M last month.",
                    citations=[Citation(source_id="R", quote="raised $50M in Series C funding")],
                )
            ],
            priorities=[],
            outreach=None,
            gaps=[],
        )

    company_id = await new_company(alice)
    await run(alice, await request_brief(alice, company_id), FakeLLMClient(inventive))

    brief = (await get_brief(alice, company_id))["brief"]
    assert (brief["claims_kept"], brief["claims_dropped"]) == (1, 1)
    assert brief["key_facts"] == []


async def test_failed_generation_is_recorded_and_still_logged(
    alice: Actor, worker_runtime: None, owner_engine: AsyncEngine
) -> None:
    company_id = await new_company(alice)
    await run(alice, await request_brief(alice, company_id), FakeLLMClient(lambda *_: None))

    result = await get_brief(alice, company_id)
    assert result["latest_run"]["status"] == "failed"
    assert result["latest_run"]["failure_reason"] == "llm_incomplete"
    assert result["brief"] is None
    async with owner_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM ai_generations")) == 1


async def test_daily_limit(alice: Actor, test_settings: Settings) -> None:
    first = await new_company(alice)
    second = await new_company(alice, name="Globex", domain="globex.com")
    app = create_app(test_settings.model_copy(update={"brief_daily_limit": 1}))
    async with client_for(app, alice) as client:
        assert (await client.post(f"/companies/{first}/brief")).status_code == 202
        refused = await client.post(f"/companies/{second}/brief")
        usage = (await client.get("/ai/usage")).json()

    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "brief_daily_limit"
    assert (usage["briefs_today"], usage["brief_daily_limit"]) == (1, 1)


async def test_unavailable_without_an_api_key(alice: Actor, test_settings: Settings) -> None:
    company_id = await new_company(alice)
    app = create_app(test_settings.model_copy(update={"llm_provider": "anthropic"}))
    async with client_for(app, alice) as client:
        response = await client.post(f"/companies/{company_id}/brief")
        usage = (await client.get("/ai/usage")).json()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "briefs_unavailable"
    assert usage["configured"] is False


async def test_ai_usage_sums_cost_by_purpose(alice: Actor, worker_runtime: None) -> None:
    company_id = await new_company(alice)
    await enrich(alice, company_id)
    await run(alice, await request_brief(alice, company_id))

    usage = (await alice.client.get("/ai/usage")).json()

    assert [p["purpose"] for p in usage["month_by_purpose"]] == ["account_brief", "company_profile"]
    assert all(p["calls"] == 1 for p in usage["month_by_purpose"])
    assert usage["cost_month_usd"] == usage["cost_today_usd"]


async def test_briefs_are_invisible_to_other_tenants(
    alice: Actor, make_client: ClientFactory, worker_runtime: None
) -> None:
    company_id = await new_company(alice)
    await run(alice, await request_brief(alice, company_id))
    mallory = await make_actor(make_client(), "mallory@evil.example.com", "Evil")

    assert (await mallory.client.get(f"/companies/{company_id}/brief")).status_code == 404
    assert (await mallory.client.post(f"/companies/{company_id}/brief")).status_code == 404
    usage = (await mallory.client.get("/ai/usage")).json()
    assert usage["month_by_purpose"] == []
