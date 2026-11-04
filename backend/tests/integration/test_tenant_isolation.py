"""Tenant isolation, enforced by PostgreSQL Row-Level Security.

Every query here runs as the restricted runtime role `sia_app`, with no application-level
filtering at all: these tests prove the *database* blocks cross-tenant access even if
application code has a bug.

Fixture world:
    org A: alice (owner), carol (member)
    org B: bob (owner), carol (admin)      <- carol belongs to both
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from sia.core.tenancy import set_tenant_context

RLS_VIOLATION = r"row-level security policy"


@dataclass(frozen=True)
class World:
    org_a: uuid.UUID
    org_b: uuid.UUID
    alice: uuid.UUID
    bob: uuid.UUID
    carol: uuid.UUID


@pytest.fixture
async def world(owner_engine: AsyncEngine) -> World:
    w = World(*(uuid.uuid4() for _ in range(5)))
    async with owner_engine.begin() as conn:  # owner bypasses RLS: set up both tenants
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:a, 'Org A'), (:b, 'Org B')"),
            {"a": w.org_a, "b": w.org_b},
        )
        await conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, name) VALUES "
                "(:alice, 'alice@a.test', 'x', 'Alice'), (:bob, 'bob@b.test', 'x', 'Bob'), "
                "(:carol, 'carol@ab.test', 'x', 'Carol')"
            ),
            {"alice": w.alice, "bob": w.bob, "carol": w.carol},
        )
        await conn.execute(
            text(
                "INSERT INTO memberships (organization_id, user_id, role) VALUES "
                "(:a, :alice, 'owner'), (:a, :carol, 'member'), "
                "(:b, :bob, 'owner'), (:b, :carol, 'admin')"
            ),
            {"a": w.org_a, "b": w.org_b, "alice": w.alice, "bob": w.bob, "carol": w.carol},
        )
    return w


@asynccontextmanager
async def as_tenant(
    engine: AsyncEngine, *, user: uuid.UUID | None, org: uuid.UUID | None
) -> AsyncIterator[AsyncConnection]:
    """A transaction as the runtime role, scoped like an authenticated request."""
    async with engine.begin() as conn:
        await set_tenant_context(conn, user_id=user, organization_id=org)
        yield conn


async def _org_ids(conn: AsyncConnection) -> set[uuid.UUID]:
    return set((await conn.execute(text("SELECT id FROM organizations"))).scalars())


async def _memberships(conn: AsyncConnection) -> set[tuple[uuid.UUID, uuid.UUID]]:
    rows = await conn.execute(text("SELECT organization_id, user_id FROM memberships"))
    return {(r.organization_id, r.user_id) for r in rows}


# --- Reads -------------------------------------------------------------------------------------


async def test_without_context_nothing_is_visible(engine: AsyncEngine, world: World) -> None:
    async with as_tenant(engine, user=None, org=None) as conn:
        assert await _org_ids(conn) == set()
        assert await _memberships(conn) == set()


async def test_tenant_sees_only_its_own_organization_data(
    engine: AsyncEngine, world: World
) -> None:
    async with as_tenant(engine, user=world.alice, org=world.org_a) as conn:
        assert await _org_ids(conn) == {world.org_a}
        assert await _memberships(conn) == {(world.org_a, world.alice), (world.org_a, world.carol)}


async def test_other_tenant_sees_only_its_own_data(engine: AsyncEngine, world: World) -> None:
    async with as_tenant(engine, user=world.bob, org=world.org_b) as conn:
        assert await _org_ids(conn) == {world.org_b}
        assert await _memberships(conn) == {(world.org_b, world.bob), (world.org_b, world.carol)}


async def test_explicitly_querying_another_tenant_returns_nothing(
    engine: AsyncEngine, world: World
) -> None:
    async with as_tenant(engine, user=world.alice, org=world.org_a) as conn:
        found = await conn.execute(
            text("SELECT * FROM memberships WHERE organization_id = :b"), {"b": world.org_b}
        )
        assert found.all() == []


async def test_user_without_active_org_sees_only_own_memberships(
    engine: AsyncEngine, world: World
) -> None:
    """Needed for the organisation switcher; must not expose other members."""
    async with as_tenant(engine, user=world.carol, org=None) as conn:
        assert await _org_ids(conn) == {world.org_a, world.org_b}
        assert await _memberships(conn) == {(world.org_a, world.carol), (world.org_b, world.carol)}


# --- Writes ------------------------------------------------------------------------------------


async def test_cannot_insert_rows_into_another_tenant(engine: AsyncEngine, world: World) -> None:
    with pytest.raises(DBAPIError, match=RLS_VIOLATION):
        async with as_tenant(engine, user=world.alice, org=world.org_a) as conn:
            await conn.execute(
                text(
                    "INSERT INTO memberships (organization_id, user_id, role) "
                    "VALUES (:b, :u, 'owner')"
                ),
                {"b": world.org_b, "u": world.alice},
            )


async def test_cannot_move_rows_into_another_tenant(engine: AsyncEngine, world: World) -> None:
    with pytest.raises(DBAPIError, match=RLS_VIOLATION):
        async with as_tenant(engine, user=world.alice, org=world.org_a) as conn:
            await conn.execute(
                text("UPDATE memberships SET organization_id = :b WHERE organization_id = :a"),
                {"a": world.org_a, "b": world.org_b},
            )


async def test_cannot_update_or_delete_another_tenants_rows(
    engine: AsyncEngine, owner_engine: AsyncEngine, world: World
) -> None:
    async with as_tenant(engine, user=world.alice, org=world.org_a) as conn:
        promoted = await conn.execute(
            text("UPDATE memberships SET role = 'member' WHERE organization_id = :b"),
            {"b": world.org_b},
        )
        deleted = await conn.execute(
            text("DELETE FROM memberships WHERE organization_id = :b"), {"b": world.org_b}
        )
        renamed = await conn.execute(
            text("UPDATE organizations SET name = 'pwned' WHERE id = :b"), {"b": world.org_b}
        )

    assert (promoted.rowcount, deleted.rowcount, renamed.rowcount) == (0, 0, 0)
    async with owner_engine.connect() as conn:  # verify B is untouched
        b_roles = (
            (
                await conn.execute(
                    text("SELECT role FROM memberships WHERE organization_id = :b ORDER BY role"),
                    {"b": world.org_b},
                )
            )
            .scalars()
            .all()
        )
        b_name = await conn.scalar(
            text("SELECT name FROM organizations WHERE id = :b"), {"b": world.org_b}
        )
    assert (list(b_roles), b_name) == (["admin", "owner"], "Org B")


async def test_member_read_access_does_not_grant_write_access(
    engine: AsyncEngine, world: World
) -> None:
    """Carol can *see* Org B while working in Org A, but must not be able to change it."""
    async with as_tenant(engine, user=world.carol, org=world.org_a) as conn:
        renamed = await conn.execute(
            text("UPDATE organizations SET name = 'pwned' WHERE id = :b"), {"b": world.org_b}
        )
    assert renamed.rowcount == 0


async def test_new_organization_requires_matching_context(engine: AsyncEngine) -> None:
    new_org, other_org = uuid.uuid4(), uuid.uuid4()

    async with as_tenant(engine, user=None, org=new_org) as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, 'New')"), {"id": new_org}
        )

    with pytest.raises(DBAPIError, match=RLS_VIOLATION):
        async with as_tenant(engine, user=None, org=new_org) as conn:
            await conn.execute(
                text("INSERT INTO organizations (id, name) VALUES (:id, 'Other')"),
                {"id": other_org},
            )


async def test_organizations_table_has_forced_rls(owner_engine: AsyncEngine) -> None:
    """`organizations` is keyed by `id`, so the organization_id guard test cannot see it."""
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'organizations' AND relkind = 'r'"
                )
            )
        ).one()
    assert tuple(row) == (True, True)
