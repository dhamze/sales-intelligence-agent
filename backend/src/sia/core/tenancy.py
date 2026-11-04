"""Multi-tenancy primitives shared by migrations and runtime code (see docs/adr/0004, 0007).

How isolation works
-------------------
1. Tenant-owned tables have an `organization_id` column and Row-Level Security (RLS) enabled
   and *forced*, with a policy comparing that column to `app_current_org_id()`.
2. For each request, after authentication, the application calls `set_tenant_context()`, which
   stores the organisation and user IDs in **transaction-local** Postgres settings.
3. `app_current_org_id()` / `app_current_user_id()` read those settings. When nothing is set they
   return NULL, and `organization_id = NULL` is never true — so a missing context returns no
   rows (fail closed) instead of everyone's rows.

Why transaction-local: connections are pooled and reused across requests. A session-level
`SET` would survive on the connection and leak one tenant's context into the next request.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from sia.core.config import APP_DB_ROLE

ORG_SETTING = "app.current_org_id"
USER_SETTING = "app.current_user_id"

DEFAULT_APP_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE")


async def set_tenant_context(
    db: AsyncSession | AsyncConnection,
    *,
    user_id: UUID | None,
    organization_id: UUID | None,
) -> None:
    """Scope the current transaction to a user and (optionally) an organisation."""
    await db.execute(
        text("SELECT set_config(:user_key, :user_id, true), set_config(:org_key, :org_id, true)"),
        {
            "user_key": USER_SETTING,
            "user_id": str(user_id) if user_id else "",
            "org_key": ORG_SETTING,
            "org_id": str(organization_id) if organization_id else "",
        },
    )


# ---------------------------------------------------------------------------------------------
# SQL used by migrations. Table names come from migration code, never from user input.
# Keep these functions stable: existing migrations depend on what they generate.
# ---------------------------------------------------------------------------------------------


def context_functions_sql() -> list[str]:
    # NULLIF(..., ''): after a transaction-local setting ends, Postgres resets a custom setting
    # to '' (not NULL), and ''::uuid would raise an error.
    return [
        f"""
        CREATE FUNCTION {name}() RETURNS uuid
        LANGUAGE sql STABLE PARALLEL SAFE
        AS $$ SELECT NULLIF(current_setting('{setting}', true), '')::uuid $$
        """
        for name, setting in (
            ("app_current_org_id", ORG_SETTING),
            ("app_current_user_id", USER_SETTING),
        )
    ]


def drop_context_functions_sql() -> list[str]:
    return ["DROP FUNCTION app_current_user_id()", "DROP FUNCTION app_current_org_id()"]


def grant_app_access_sql(table: str, privileges: tuple[str, ...] = DEFAULT_APP_PRIVILEGES) -> str:
    return f"GRANT {', '.join(privileges)} ON TABLE {table} TO {APP_DB_ROLE}"


def enable_rls_sql(table: str) -> list[str]:
    # FORCE makes the policies apply to the table owner too (superusers still bypass RLS,
    # which is why the application never connects as one).
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
    ]


def tenant_isolation_policy_sql(table: str, column: str = "organization_id") -> str:
    """Standard policy: rows are visible and writable only within the current organisation."""
    return (
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({column} = app_current_org_id()) "
        f"WITH CHECK ({column} = app_current_org_id())"
    )
