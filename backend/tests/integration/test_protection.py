"""Abuse and cost protection: rate limits, the per-organisation AI switch and the AI budget."""

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from decimal import Decimal
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
from sia.modules.insights import service as insights
from sia.modules.insights.providers import fake_brief
from sia.modules.protection import rate_limit
from sia.worker import runtime
from tests.integration.conftest import ClientFactory
from tests.integration.helpers import PASSWORD, Actor, make_actor

# A client factory that can pretend to be any client IP address.
IpClientFactory = Callable[..., httpx.AsyncClient]


@asynccontextmanager
async def running(
    settings: Settings, ip: str = "203.0.113.7"
) -> AsyncIterator[tuple[FastAPI, IpClientFactory]]:
    """An app with its own settings; clients appear to come from `ip` unless told otherwise."""
    app = create_app(settings)
    clients: list[httpx.AsyncClient] = []

    def client(from_ip: str = ip) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app, client=(from_ip, 4000))
        c = httpx.AsyncClient(transport=transport, base_url="http://test")
        clients.append(c)
        return c

    async with app.router.lifespan_context(app):
        try:
            yield app, client
        finally:
            for c in clients:
                await c.aclose()


def signup_body(email: str) -> dict[str, Any]:
    return {"email": email, "password": PASSWORD, "name": "Ann", "organization_name": "Org"}


@pytest.fixture
async def worker_runtime(test_settings: Settings) -> AsyncIterator[None]:
    runtime.init(test_settings)
    yield
    await runtime.dispose()


# --- Rate limiting --------------------------------------------------------------------------


async def test_writes_are_limited_per_ip_with_retry_after(test_settings: Settings) -> None:
    settings = test_settings.model_copy(
        update={"rate_limit_enabled": True, "rate_limit_writes_per_minute": 3}
    )
    async with running(settings) as (_, client):
        c = client()
        statuses = [
            (await c.post("/auth/login", json={"email": "x@y.com", "password": "nope"})).status_code
            for _ in range(4)
        ]
        refused = await c.post("/auth/login", json={"email": "x@y.com", "password": "nope"})
        reads_still_work = await c.get("/auth/me")
        other_ip = await client("198.51.100.9").post(
            "/auth/login", json={"email": "x@y.com", "password": "nope"}
        )

    assert statuses[:3] == [401, 401, 401]
    assert statuses[3] == 429
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(refused.headers["retry-after"]) <= 60
    assert reads_still_work.status_code == 401  # reads have their own, higher limit
    assert other_ip.status_code == 401  # every client IP has its own counter


async def test_signups_are_limited_per_hour(test_settings: Settings) -> None:
    settings = test_settings.model_copy(
        update={"rate_limit_enabled": True, "rate_limit_signups_per_hour": 2}
    )
    async with running(settings) as (_, client):
        results = [
            (await client().post("/auth/signup", json=signup_body(f"u{i}@example.com"))).status_code
            for i in range(3)
        ]
    assert results == [201, 201, 429]


async def test_health_checks_are_never_limited(test_settings: Settings) -> None:
    settings = test_settings.model_copy(
        update={"rate_limit_enabled": True, "rate_limit_requests_per_minute": 2}
    )
    async with running(settings) as (_, client):
        c = client()
        statuses = {(await c.get("/health/live")).status_code for _ in range(5)}
    assert statuses == {200}


async def test_client_ips_are_stored_only_as_hashes(
    test_settings: Settings, owner_engine: AsyncEngine
) -> None:
    async with running(test_settings.model_copy(update={"rate_limit_enabled": True})) as (
        _,
        client,
    ):
        await client("203.0.113.7").get("/auth/me")
    async with owner_engine.connect() as conn:
        keys = (await conn.execute(text("SELECT key FROM rate_limit_hits"))).scalars().all()
    assert keys
    assert not any("203.0.113.7" in k for k in keys)


async def test_rate_limiting_fails_open_when_the_database_errors(
    test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_: object) -> None:
        raise ConnectionError("database unreachable")

    monkeypatch.setattr(rate_limit, "hit", broken)
    async with running(test_settings.model_copy(update={"rate_limit_enabled": True})) as (
        _,
        client,
    ):
        assert (await client().get("/auth/me")).status_code == 401  # served, not blocked


# --- AI access --------------------------------------------------------------------------------


async def test_public_signups_get_no_ai_until_an_operator_enables_it(
    test_settings: Settings, owner_engine: AsyncEngine
) -> None:
    settings = test_settings.model_copy(update={"ai_enabled_for_new_orgs": False})
    async with running(settings) as (_, client):
        c = client()
        me = (await c.post("/auth/signup", json=signup_body("demo@example.com"))).json()
        company = (await c.post("/companies", json={"name": "Initech", "domain": "i.com"})).json()

        refused = await c.post(f"/companies/{company['id']}/enrich")
        usage = (await c.get("/enrichment/usage")).json()
        brief = await c.post(f"/companies/{company['id']}/brief")

        async with owner_engine.begin() as conn:  # what `sia.scripts.ai_access --on` does
            await conn.execute(
                text("UPDATE organizations SET ai_enabled = true WHERE id = :id"),
                {"id": me["active_organization"]["id"]},
            )
        allowed = await c.post(f"/companies/{company['id']}/enrich")

    assert refused.status_code == 503
    assert refused.json()["error"]["details"] == [{"reason": "disabled_for_org"}]
    assert (usage["available"], usage["unavailable_reason"]) == (False, "disabled_for_org")
    assert brief.json()["error"]["details"] == [{"reason": "disabled_for_org"}]
    assert allowed.status_code == 202


# --- AI budget --------------------------------------------------------------------------------


async def _spend(owner_engine: AsyncEngine, amount: str) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO ai_spend_days (day, calls, cost_usd) VALUES (current_date, 1, :c)"),
            {"c": Decimal(amount)},
        )


async def test_spent_budget_pauses_ai_for_everyone(
    test_settings: Settings, owner_engine: AsyncEngine, make_client: ClientFactory
) -> None:
    alice = await make_actor(make_client(), "alice@acme.example.com", "Acme")
    company_id = (
        await alice.client.post("/companies", json={"name": "Initech", "domain": "i.com"})
    ).json()["id"]
    await _spend(owner_engine, "10.50")
    settings = test_settings.model_copy(update={"ai_monthly_budget_usd": Decimal("10")})
    async with running(settings) as (_, client):
        c = client()
        c.cookies.update(alice.client.cookies)
        refused = await c.post(f"/companies/{company_id}/brief")
        usage = (await c.get("/ai/usage")).json()

    assert refused.status_code == 503
    assert refused.json()["error"]["details"] == [{"reason": "budget_exhausted"}]
    assert usage["unavailable_reason"] == "budget_exhausted"


async def test_queued_jobs_stop_when_the_budget_runs_out_meanwhile(
    alice_and_company: tuple[Actor, str], owner_engine: AsyncEngine, worker_runtime: None
) -> None:
    alice, company_id = alice_and_company
    queued = (await alice.client.post(f"/companies/{company_id}/brief")).json()
    await _spend(owner_engine, "11")  # spent by other organisations while the job waited
    llm = FakeLLMClient(fake_brief)

    await insights.run_brief(
        organization_id=alice.org_id,
        company_id=uuid.UUID(company_id),
        run_id=uuid.UUID(queued["id"]),
        llm=llm,
        budget=Decimal("10"),
    )

    result = (await alice.client.get(f"/companies/{company_id}/brief")).json()
    assert result["latest_run"]["failure_reason"] == "ai_budget_exhausted"
    assert llm.calls == []  # the model was never called


async def test_every_ai_call_adds_to_the_daily_spend_total(
    alice_and_company: tuple[Actor, str], owner_engine: AsyncEngine, worker_runtime: None
) -> None:
    alice, company_id = alice_and_company
    queued = (await alice.client.post(f"/companies/{company_id}/enrich")).json()
    await enrichment.run_enrichment(
        organization_id=alice.org_id,
        company_id=uuid.UUID(company_id),
        run_id=uuid.UUID(queued["id"]),
        reader=FakeSiteReader(),
        llm=FakeLLMClient(fake_profile),
    )
    async with owner_engine.connect() as conn:
        calls, cost = (await conn.execute(text("SELECT calls, cost_usd FROM ai_spend_days"))).one()
        logged = await conn.scalar(text("SELECT sum(cost_usd) FROM ai_generations"))
    assert calls == 1
    assert cost == logged > 0


@pytest.fixture
async def alice_and_company(make_client: ClientFactory) -> tuple[Actor, str]:
    alice = await make_actor(make_client(), "alice@acme.example.com", "Acme")
    response = await alice.client.post("/companies", json={"name": "Initech", "domain": "i.com"})
    return alice, response.json()["id"]
