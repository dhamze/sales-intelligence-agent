# ADR-0008: Fuzzy search under Row-Level Security

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

Company and contact search uses `pg_trgm` (typo-tolerant `word_similarity`, plus `ILIKE`),
backed by GIN trigram indexes. Measured on 50,000 companies in one organisation, connected as
the runtime role `sia_app`:

| Query | With RLS (production setup) | Same query without RLS |
|---|---|---|
| List / sort / paginate | 0.2 ms (index) | — |
| Fuzzy search | ~190 ms (sequential scan) | ~10 ms (trigram index) |

Under RLS, PostgreSQL only evaluates *leakproof* functions before the security policy, because a
non-leakproof function could reveal data from rows the user may not see. None of the text-search
operators are leakproof (`word_similarity_op`, `similarity_op`, `texticlike`, `textlike`,
`ts_match_*`); only equality and `starts_with` are. So the trigram indexes cannot be used and
search cost grows with the size of each tenant's data (not with the size of the whole table).

## Options considered

1. **Keep as is.** Correct and isolated; ~10–40 ms for tenants with 2,000–10,000 companies,
   the expected range for the target customers (sales teams of 5–200 people).
2. **SECURITY DEFINER search function** owned by a dedicated `NOLOGIN BYPASSRLS` role, filtering
   by `app_current_org_id()` itself and returning only IDs and scores, with the outer query still
   under RLS. Index-backed (~10 ms) but adds a contained exception to "nothing bypasses RLS",
   and support for `BYPASSRLS` roles depends on the managed-PostgreSQL host (chosen in Phase 8).
3. **Mark the operators `LEAKPROOF`.** Rejected: requires superuser, changes a global catalog
   property of core and extension functions, impossible on managed PostgreSQL.

## Decision

Option 1 for now. Revisit when any tenant approaches ~20,000 companies, or in Phase 8 once the
hosting provider is known (option 2 is the planned path).

## Consequences

- Search latency is a known, measured, tenant-local cost.
- A performance regression test guards the current behaviour.
- No new privileged database roles.
