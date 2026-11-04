# ADR-0004: Shared-schema multi-tenancy with Row-Level Security

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

Each customer organisation's data must be strictly isolated. Options: database per tenant,
schema per tenant, or a shared schema with a tenant column.

## Decision

Shared schema. Every tenant-owned table has a non-null `organization_id`. Isolation is enforced
in two independent layers:

1. **Application:** repositories always filter by the current organisation.
2. **Database:** PostgreSQL **Row-Level Security** policies compare `organization_id` with a
   per-transaction setting (`SET LOCAL app.current_org_id`). The application connects as a
   role that cannot bypass RLS.

## Consequences

- Simple operations (one schema, one migration path) that scale to many tenants.
- A missing filter in application code does not leak data — the database still blocks it.
- An automated test suite attempts cross-tenant reads and writes on every tenant table.
- Migrations and background jobs must set the tenant context explicitly; admin tasks use a
  separate, audited role.
