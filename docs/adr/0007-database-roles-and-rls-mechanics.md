# ADR-0007: Database roles and Row-Level Security mechanics

- **Status:** Accepted
- **Date:** 2026-11-04
- **Refines:** [ADR-0004](0004-multi-tenancy-rls.md)

## Context

ADR-0004 chose shared-schema multi-tenancy enforced by PostgreSQL Row-Level Security (RLS).
Implementing it surfaced three facts that determine whether RLS actually protects anything:

1. **Superusers, and roles with `BYPASSRLS`, ignore RLS entirely.** The role created by the
   Postgres Docker image is a superuser.
2. **Table owners ignore RLS** unless the table uses `FORCE ROW LEVEL SECURITY`.
3. **Connections are pooled.** A session-level `SET` survives on a connection and would leak one
   request's tenant into the next request that reuses it. Also, after a transaction-local custom
   setting ends, Postgres resets it to `''` (not `NULL`), and `''::uuid` raises an error.

## Decision

**Two database roles.**

| Role | Used by | Attributes |
|---|---|---|
| `sia` (owner) | Migrations, admin tasks, test setup | Owns the schema |
| `sia_app` | The running API (and later the worker) | `NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`; only table-level DML granted per table by migrations; cannot read `alembic_version` |

`sia_app` is created by `infra/postgres/init/02-create-app-role.sh` (idempotent; used by Docker
Compose and CI). Its name is fixed in code because migrations grant privileges to it by name.

**RLS conventions.**

- Tenant tables have `organization_id`, `ENABLE` + `FORCE ROW LEVEL SECURITY`, and the
  `tenant_isolation` policy: `USING/WITH CHECK (organization_id = app_current_org_id())`.
- `app_current_org_id()` / `app_current_user_id()` read transaction-local settings with
  `NULLIF(current_setting(..., true), '')::uuid`. Unset context therefore yields `NULL`, which
  matches no rows: **fail closed**.
- Each request sets context with `set_config(..., is_local => true)` after authentication.
- Extra read-only policies exist only where a feature needs them: users can read their own
  memberships and the organisations they belong to (organisation switcher).
- Helpers in `sia/core/tenancy.py` generate the SQL so every table follows the same pattern.

**Non-tenant tables** (`users`, `sessions`, `login_attempts`) have no RLS: they are read before
any organisation is known. They are accessed only through the identity module's repository.

**Guard rails (automated tests).**

- Every table with an `organization_id` column must have forced RLS and a policy.
- `sia_app` must not be a superuser or bypass RLS, and cannot change the schema or `SET ROLE`.
- A cross-tenant attack suite (read, insert, move, update, delete) runs as `sia_app`.
  A deliberate sabotage run (RLS removed from one table) made 9 tests fail.

## Consequences

- A forgotten `WHERE organization_id = ...` in application code returns no foreign rows.
- Every new tenant table needs its migration to call the tenancy helpers; the guard test fails
  the build if it does not.
- Background jobs must set tenant context explicitly before touching tenant data.
- Managed databases (production) must provide an equivalent non-superuser runtime role; the
  deployment phase will provision it the same way.
