"""Enrichment end to end against the real database (fake website + fake AI, never the network)."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import procrastinate
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sia.ai.client import FakeLLMClient, Outcome, StructuredResult
from sia.core.config import Settings
from sia.main import create_app
from sia.modules.enrichment import service, tasks
from sia.modules.enrichment.extraction import Evidence, ExtractedProfile, TextFact
from sia.modules.enrichment.fetcher import FetchError, FetchFailure
from sia.modules.enrichment.providers import FakeSiteReader, fake_profile
from sia.worker import configured_app, runtime
from tests.integration.conftest import ClientFactory
from tests.integration.helpers import Actor, make_actor


@pytest.fixture
async def worker_runtime(test_settings: Settings) -> AsyncIterator[None]:
    runtime.init(test_settings)
    yield
    await runtime.dispose()


@asynccontextmanager
async def client_for(app: FastAPI, actor: Actor) -> AsyncIterator[httpx.AsyncClient]:
    """The actor's browser session, against a differently configured app."""
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        client.cookies.update(actor.client.cookies)
        yield client


@pytest.fixture
async def alice(make_client: ClientFactory) -> Actor:
    return await make_actor(make_client(), "alice@acme.example.com", "Acme")


async def new_company(actor: Actor, **fields: Any) -> str:
    response = await actor.client.post(
        "/companies", json={"name": "Initech", "domain": "initech.com", **fields}
    )
    assert response.status_code == 201, response.text
    company_id: str = response.json()["id"]
    return company_id


async def request(actor: Actor, company_id: str) -> dict[str, Any]:
    response = await actor.client.post(f"/companies/{company_id}/enrich")
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


async def run(actor: Actor, run: dict[str, Any], *, reader: Any = None, llm: Any = None) -> None:
    await service.run_enrichment(
        organization_id=actor.org_id,
        company_id=uuid.UUID(run["company_id"]),
        run_id=uuid.UUID(run["id"]),
        reader=reader or FakeSiteReader(),
        llm=llm or FakeLLMClient(fake_profile),
    )


async def enrichment(actor: Actor, company_id: str) -> dict[str, Any]:
    body: dict[str, Any] = (await actor.client.get(f"/companies/{company_id}/enrichment")).json()
    return body


async def test_request_creates_a_run_and_a_job_in_one_go(
    alice: Actor, owner_engine: AsyncEngine
) -> None:
    company_id = await new_company(alice)

    first = await request(alice, company_id)
    again = await request(alice, company_id)  # already queued: same run, no duplicate job

    assert first["status"] == "queued"
    assert again["id"] == first["id"]
    async with owner_engine.connect() as conn:
        jobs = (
            (
                await conn.execute(
                    text("SELECT args FROM procrastinate_jobs WHERE task_name = :t"),
                    {"t": service.TASK_NAME},
                )
            )
            .scalars()
            .all()
        )
    assert [j["run_id"] for j in jobs] == [first["id"]]


async def test_successful_enrichment_stores_verified_profile_and_fills_only_empty_fields(
    alice: Actor, worker_runtime: None
) -> None:
    company_id = await new_company(alice, industry="Banking (curated)")
    queued = await request(alice, company_id)

    await run(alice, queued)

    result = await enrichment(alice, company_id)
    assert result["latest_run"]["status"] == "succeeded"
    profile = result["profile"]
    assert profile["facts"]["headquarters_city"]["value"] == "Berlin"
    assert profile["facts"]["description"]["evidence"][0]["source_url"] == "https://initech.com/"
    assert profile["facts_dropped"] == 0
    company = (await alice.client.get(f"/companies/{company_id}")).json()
    assert company["industry"] == "Banking (curated)"  # existing value kept
    assert (company["city"], company["country"]) == ("Berlin", "Germany")  # empty ones filled
    assert company["description"].startswith("Workflow automation software")


async def test_invented_facts_are_dropped_and_counted(alice: Actor, worker_runtime: None) -> None:
    def hallucinating(system: str, content: str, output_type: type[Any]) -> ExtractedProfile:
        profile = fake_profile(system, content, output_type)
        assert isinstance(profile, ExtractedProfile)
        return profile.model_copy(
            update={
                "headquarters_city": TextFact(
                    value="Paris",
                    evidence=[Evidence(source_url="https://initech.com/", quote="based in Paris")],
                )
            }
        )

    company_id = await new_company(alice)
    await run(alice, await request(alice, company_id), llm=FakeLLMClient(hallucinating))

    result = await enrichment(alice, company_id)
    assert "headquarters_city" not in result["profile"]["facts"]
    assert result["profile"]["facts_dropped"] == 1
    company = (await alice.client.get(f"/companies/{company_id}")).json()
    assert company["city"] is None  # nothing unverified reaches the company record


class BlockedSite:
    async def read(self, website: str) -> list[Any]:
        raise FetchError(FetchFailure.ROBOTS_DISALLOWED, website)


class RefusingLLM:
    model = "claude-opus-5-5"

    async def extract(self, **_: Any) -> StructuredResult[Any]:
        return StructuredResult(
            outcome=Outcome.REFUSED, output=None, model=self.model,
            input_tokens=5000, output_tokens=10,
        )  # fmt: skip


@pytest.mark.parametrize(
    ("reader", "llm", "reason"),
    [
        (BlockedSite(), None, "fetch_robots_disallowed"),
        (None, RefusingLLM(), "llm_refused"),
    ],
)
async def test_failures_are_recorded_with_a_reason(
    alice: Actor, worker_runtime: None, reader: Any, llm: Any, reason: str
) -> None:
    company_id = await new_company(alice)
    await run(alice, await request(alice, company_id), reader=reader, llm=llm)

    result = await enrichment(alice, company_id)
    assert result["latest_run"]["status"] == "failed"
    assert result["latest_run"]["failure_reason"] == reason
    assert result["profile"] is None


async def test_every_ai_call_is_costed_including_refusals(
    alice: Actor, worker_runtime: None
) -> None:
    company_id = await new_company(alice)
    await run(alice, await request(alice, company_id), llm=RefusingLLM())

    usage = (await alice.client.get("/enrichment/usage")).json()

    assert usage["used_today"] == 1
    assert float(usage["cost_today_usd"]) > 0  # 5,000 input tokens on Opus 5.5


async def test_company_without_website_fails_cleanly(alice: Actor, worker_runtime: None) -> None:
    company_id = await new_company(alice, domain=None)
    await run(alice, await request(alice, company_id))

    assert (await enrichment(alice, company_id))["latest_run"]["failure_reason"] == "no_website"


async def test_daily_limit(test_settings: Settings, alice: Actor) -> None:
    ids = [await new_company(alice, name=f"C{i}", domain=f"company-{i}.com") for i in range(3)]
    capped = create_app(test_settings.model_copy(update={"enrichment_daily_limit": 2}))

    async with client_for(capped, alice) as client:
        ok = await client.post("/enrichment/runs", json={"company_ids": ids[:2]})
        over = await client.post("/enrichment/runs", json={"company_ids": ids[2:]})

    assert ok.status_code == 202
    assert over.status_code == 429
    assert over.json()["error"]["code"] == "enrichment_daily_limit"


async def test_unconfigured_ai_gives_a_clear_503(test_settings: Settings, alice: Actor) -> None:
    company_id = await new_company(alice)
    unconfigured = create_app(test_settings.model_copy(update={"llm_provider": "anthropic"}))

    async with client_for(unconfigured, alice) as client:
        response = await client.post(f"/companies/{company_id}/enrich")
        usage = (await client.get("/enrichment/usage")).json()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_unavailable"
    assert response.json()["error"]["details"] == [{"reason": "not_configured"}]
    assert (usage["available"], usage["unavailable_reason"]) == (False, "not_configured")


async def test_bulk_enrich_not_yet_enriched_companies(alice: Actor) -> None:
    for i in range(3):
        await new_company(alice, name=f"C{i}", domain=f"company-{i}.com")
    await new_company(alice, name="No site", domain=None)  # can't be enriched: skipped

    runs = (await alice.client.post("/enrichment/runs", json={"not_yet_enriched": True})).json()
    again = (await alice.client.post("/enrichment/runs", json={"not_yet_enriched": True})).json()

    assert len(runs) == 3
    assert again == []  # all already attempted


async def test_other_tenants_cannot_see_or_trigger_enrichment(
    alice: Actor, make_client: ClientFactory, worker_runtime: None
) -> None:
    company_id = await new_company(alice)
    await run(alice, await request(alice, company_id))
    bob = await make_actor(make_client(), "bob@globex.example.com", "Globex")

    assert (await bob.client.get(f"/companies/{company_id}/enrichment")).status_code == 404
    assert (await bob.client.post(f"/companies/{company_id}/enrich")).status_code == 404
    bulk = await bob.client.post("/enrichment/runs", json={"company_ids": [company_id]})
    assert bulk.status_code == 404


async def test_the_real_worker_runs_the_task(
    alice: Actor, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through Procrastinate itself: enqueue via the API, process with the worker."""
    monkeypatch.setattr(tasks, "get_settings", lambda: test_settings)  # fake providers
    company_id = await new_company(alice)
    await request(alice, company_id)

    runtime.init(test_settings)
    worker: procrastinate.App = configured_app(test_settings)
    try:
        async with worker.open_async():
            await worker.run_worker_async(
                queues=[service.QUEUE], wait=False, install_signal_handlers=False,
                listen_notify=False,
            )  # fmt: skip
    finally:
        await runtime.dispose()

    result = await enrichment(alice, company_id)
    assert result["latest_run"]["status"] == "succeeded"
    assert result["profile"]["facts"]["industry"]["value"] == "Fintech"
