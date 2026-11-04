"""The runtime database role must be unable to weaken its own isolation."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from sia.core.config import APP_DB_ROLE
from sia.core.tenancy import set_tenant_context


async def test_api_connects_as_restricted_role(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()

    assert row.current_user == APP_DB_ROLE
    assert not row.rolsuper, "superusers bypass Row-Level Security"
    assert not row.rolbypassrls
    assert not row.rolcreaterole
    assert not row.rolcreatedb


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE sneaky (id int)",
        "ALTER FUNCTION app_current_org_id() RENAME TO hijacked",
        "DROP FUNCTION app_current_org_id()",
        "SET ROLE sia",
    ],
)
async def test_restricted_role_cannot_change_schema_or_escalate(
    engine: AsyncEngine, statement: str
) -> None:
    async with engine.connect() as conn:
        with pytest.raises(DBAPIError, match=r"permission denied|must be owner"):
            await conn.execute(text(statement))


async def test_tenant_context_is_scoped_to_one_transaction(engine: AsyncEngine) -> None:
    """Pooled connections are reused: context must not survive into the next transaction."""
    org_id, user_id = uuid.uuid4(), uuid.uuid4()

    # Both transactions run on the same physical connection, as happens with pooling.
    async with engine.connect() as conn:
        async with conn.begin():
            await set_tenant_context(conn, user_id=user_id, organization_id=org_id)
            inside = (
                await conn.execute(text("SELECT app_current_org_id(), app_current_user_id()"))
            ).one()

        async with conn.begin():
            after = (
                await conn.execute(text("SELECT app_current_org_id(), app_current_user_id()"))
            ).one()

    assert tuple(inside) == (org_id, user_id)
    assert tuple(after) == (None, None)  # NULL, not '' -> no "invalid uuid" error, fails closed


async def test_context_functions_return_null_when_never_set(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT app_current_org_id(), app_current_user_id()"))).one()

    assert tuple(row) == (None, None)


async def test_every_tenant_table_has_forced_rls_and_a_policy(owner_engine: AsyncEngine) -> None:
    """Guard rail for future tables: any table with an organization_id column must be isolated."""
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                           (SELECT count(*) FROM pg_policies p
                            WHERE p.schemaname = 'public' AND p.tablename = c.relname) AS policies
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relkind = 'r'
                      AND EXISTS (SELECT 1 FROM information_schema.columns col
                                  WHERE col.table_schema = 'public'
                                    AND col.table_name = c.relname
                                    AND col.column_name = 'organization_id')
                    """
                )
            )
        ).all()

    unprotected = [r.relname for r in rows if not (r.relrowsecurity and r.relforcerowsecurity)]
    without_policy = [r.relname for r in rows if r.policies == 0]
    assert unprotected == [], f"tables without forced RLS: {unprotected}"
    assert without_policy == [], f"tables without an RLS policy: {without_policy}"
