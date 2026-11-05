# ADR-0015: Fuzzy search under RLS, revisited for self-hosted PostgreSQL

- **Status:** Accepted (confirms ADR-0008 option 1; adds a revisit trigger)
- **Date:** 2026-11-05

## Context

ADR-0008 kept fuzzy search as a sequential scan under Row-Level Security (~190 ms at 50,000
companies in one tenant, ~10–40 ms at 2,000–10,000) and deferred the alternative, an
index-backed SECURITY DEFINER search function owned by a `BYPASSRLS` role, until hosting was
known. Phase 8 chose a self-managed VPS: PostgreSQL runs in our own container, we are
superuser, so every option in ADR-0008 is now technically possible.

## Decision

Keep option 1 (search entirely under RLS, no exceptions).

- The public demo's tenants are tiny (12 sample companies; signups are rate limited), so the
  index would buy nothing visible today.
- Option 2 adds the one code path that is allowed to read across tenants. Its correctness
  would rest on hand-written filtering inside a privileged function; RLS's value is precisely
  that no such path exists.
- Option 3 (marking operators `LEAKPROOF`) stays rejected: it changes global catalog
  properties of core and extension functions for every database on the server.

**Revisit trigger** (any of): a tenant passes ~20,000 companies; search p95 above 300 ms in
production logs (the request log records `duration_ms` per request); or a paying customer's
expected data volume exceeds that. The first step then is option 2 behind a feature flag, with
the existing tenant-isolation tests run against it.

## Consequences

- No change to code. Search latency stays proportional to each tenant's own data.
- The performance regression test from ADR-0008 continues to guard the current behaviour.
