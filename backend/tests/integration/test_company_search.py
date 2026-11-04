"""Search, filters and cursor pagination for companies (and contacts)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import ClientFactory
from tests.integration.helpers import Actor, make_actor


@pytest.fixture
async def alice(make_client: ClientFactory) -> Actor:
    return await make_actor(make_client(), "alice@acme.example.com", "Acme")


async def insert_companies(
    owner_engine: AsyncEngine, org_id: uuid.UUID, rows: list[dict[str, Any]]
) -> None:
    """Bulk insert in ONE statement: every row gets the same created_at (worst case for
    pagination, since only the id tie-breaker keeps the order total)."""
    defaults = {
        "domain": None,
        "industry": None,
        "employee_count": None,
        "country": None,
        "source": "manual",
    }
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO companies "
                "(organization_id, name, domain, industry, employee_count, country, source) "
                "VALUES (:org, :name, :domain, :industry, :employee_count, :country, :source)"
            ),
            [{"org": org_id, **defaults, **row} for row in rows],
        )


async def collect_all(actor: Actor, path: str, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = None
    for _ in range(100):  # safety stop
        query = {**params, **({"cursor": cursor} if cursor else {})}
        response = await actor.client.get(path, params=query)
        assert response.status_code == 200, response.text
        page = response.json()
        items.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            return items
    raise AssertionError("pagination did not terminate")


# --- Pagination --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sort", ["name", "-name", "created_at", "-created_at", "updated_at", "-updated_at"]
)
async def test_paging_returns_every_row_exactly_once(
    alice: Actor, owner_engine: AsyncEngine, sort: str
) -> None:
    # 60 rows, only 3 distinct names, identical timestamps: heavy ties in every sort column.
    await insert_companies(
        owner_engine, alice.org_id, [{"name": f"Company {i % 3}"} for i in range(60)]
    )

    items = await collect_all(alice, "/companies", sort=sort, limit=7)

    ids = [c["id"] for c in items]
    assert len(ids) == 60
    assert len(set(ids)) == 60
    if sort.lstrip("-") == "name":
        names = [c["name"] for c in items]
        assert names == sorted(names, reverse=sort.startswith("-"))


async def test_rows_added_during_paging_do_not_duplicate_or_skip_existing_rows(
    alice: Actor, owner_engine: AsyncEngine
) -> None:
    await insert_companies(owner_engine, alice.org_id, [{"name": f"C{i:02}"} for i in range(20)])
    first = (await alice.client.get("/companies", params={"sort": "name", "limit": 10})).json()

    # Someone inserts rows that sort *before* the current position (offset paging would shift).
    await insert_companies(owner_engine, alice.org_id, [{"name": "A-new"}, {"name": "B-new"}])
    second = (
        await alice.client.get(
            "/companies", params={"sort": "name", "limit": 10, "cursor": first["next_cursor"]}
        )
    ).json()

    names = [c["name"] for c in first["items"] + second["items"]]
    assert names == [f"C{i:02}" for i in range(20)]


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({"cursor": "garbage"}, 400),
        ({"limit": 0}, 422),
        ({"limit": 101}, 422),
        ({"sort": "password_hash"}, 422),  # only whitelisted sort keys
        ({"unknown": "x"}, 422),
    ],
)
async def test_invalid_list_parameters(alice: Actor, params: dict[str, Any], status: int) -> None:
    assert (await alice.client.get("/companies", params=params)).status_code == status


async def test_cursor_cannot_be_reused_with_a_different_sort(
    alice: Actor, owner_engine: AsyncEngine
) -> None:
    await insert_companies(owner_engine, alice.org_id, [{"name": f"C{i}"} for i in range(5)])
    page = (await alice.client.get("/companies", params={"sort": "name", "limit": 2})).json()

    response = await alice.client.get(
        "/companies", params={"sort": "-created_at", "cursor": page["next_cursor"]}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cursor"


# --- Search ------------------------------------------------------------------------------------

SEARCH_FIXTURE = [
    {"name": "Acme Corporation", "domain": "acme.com"},
    {"name": "Acme Labs", "domain": "acmelabs.io"},
    {"name": "Globex", "domain": "globex.com"},
    {"name": "Initech", "domain": "initech.com"},
    {"name": "100% Organic Foods", "domain": "organic.example.com"},
]


async def search(actor: Actor, q: str, **params: Any) -> list[str]:
    response = await actor.client.get("/companies", params={"q": q, **params})
    assert response.status_code == 200, response.text
    return [c["name"] for c in response.json()["items"]]


async def test_search_tolerates_typos_and_ranks_by_relevance(
    alice: Actor, owner_engine: AsyncEngine
) -> None:
    await insert_companies(owner_engine, alice.org_id, SEARCH_FIXTURE)

    results = await search(alice, "acmee corp")

    assert results[0] == "Acme Corporation"
    assert "Globex" not in results


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("globex.com", ["Globex"]),  # domain match
        ("INITECH", ["Initech"]),  # case-insensitive
        ("labs", ["Acme Labs"]),  # word inside the name
        ("100%", ["100% Organic Foods"]),  # % is literal, not a wildcard
        ("_", []),  # _ is literal, not "any character"
    ],
)
async def test_search_matches(
    alice: Actor, owner_engine: AsyncEngine, q: str, expected: list[str]
) -> None:
    await insert_companies(owner_engine, alice.org_id, SEARCH_FIXTURE)

    assert await search(alice, q) == expected


async def test_search_results_paginate_by_relevance(
    alice: Actor, owner_engine: AsyncEngine
) -> None:
    await insert_companies(
        owner_engine, alice.org_id, [{"name": f"Acme Branch {i}"} for i in range(12)]
    )

    items = await collect_all(alice, "/companies", q="acme", limit=5)

    assert len({c["id"] for c in items}) == 12


async def test_search_never_crosses_tenants(
    alice: Actor, make_client: ClientFactory, owner_engine: AsyncEngine
) -> None:
    bob = await make_actor(make_client(), "bob@globex.example.com", "Globex")
    await insert_companies(owner_engine, bob.org_id, SEARCH_FIXTURE)

    assert await search(alice, "acme") == []


# --- Filters -----------------------------------------------------------------------------------


async def test_filters_combine(alice: Actor, owner_engine: AsyncEngine) -> None:
    await insert_companies(
        owner_engine,
        alice.org_id,
        [
            {"name": "A", "industry": "Software", "employee_count": 50, "country": "US"},
            {"name": "B", "industry": "software", "employee_count": 500, "country": "DE"},
            {"name": "C", "industry": "Fintech", "employee_count": 80, "country": "US"},
            {"name": "D", "industry": "Retail", "employee_count": None, "country": "US"},
            {
                "name": "E",
                "industry": "Fintech",
                "employee_count": 20,
                "country": "us",
                "source": "import",
            },
        ],
    )

    async def names(**params: Any) -> list[str]:
        items = await collect_all(alice, "/companies", sort="name", **params)
        return [c["name"] for c in items]

    assert await names(industry="SOFTWARE") == ["A", "B"]  # case-insensitive
    assert await names(industry=["Software", "Fintech"], country="US") == ["A", "C", "E"]
    assert await names(employees_min=50, employees_max=100) == ["A", "C"]
    assert await names(source="import") == ["E"]
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert await names(created_after=tomorrow) == []


async def test_contacts_search_and_pagination(alice: Actor) -> None:
    for first, last in [("Peter", "Gibbons"), ("Michael", "Bolton"), ("Samir", "Nagheenanajar")]:
        response = await alice.client.post(
            "/contacts", json={"first_name": first, "last_name": last}
        )
        assert response.status_code == 201

    by_name = await collect_all(alice, "/contacts", sort="full_name", limit=1)
    found = (await alice.client.get("/contacts", params={"q": "micheal bolton"})).json()

    assert [c["full_name"] for c in by_name] == [
        "Michael Bolton",
        "Peter Gibbons",
        "Samir Nagheenanajar",
    ]
    assert found["items"][0]["full_name"] == "Michael Bolton"  # despite the typo
