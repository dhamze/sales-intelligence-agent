# ADR-0013: Abuse and cost protection for a public deployment

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

The public demo lets anyone sign up, and AI calls are paid for by the operator. Without limits,
one script could fill the database, guess passwords at scale, or spend the AI budget in an
afternoon. The deployment is a single small server (ADR: Phase 8 hosting decision).

## Decision

1. **Rate limiting in PostgreSQL, not Redis.** Fixed one-minute (and one-hour) windows per client
   IP: 600 requests/min overall, 60 writes/min, 5 signups/hour. Each request increments its
   counters in ONE upsert into an `UNLOGGED` table; exceeding a limit returns 429 with
   `Retry-After`. Counters are shared by all API processes. Expired windows are deleted by the
   requests themselves (about 1 in 500), so no scheduler is needed. Health checks are exempt.
2. **Privacy:** client IPs are stored only as truncated SHA-256 hashes.
3. **Fail open:** if the counter update fails, the request proceeds (the API needs the database
   anyway; blocking everything would turn a blip into an outage). Login has its own,
   fail-closed brute-force protection (ADR-0003).
4. **AI is a per-organisation permission.** `organizations.ai_enabled`; new signups get
   `SIA_AI_ENABLED_FOR_NEW_ORGS` (false on the public demo). Operators switch it with
   `python -m sia.scripts.ai_access`. Not changeable through the API.
5. **A global monthly AI budget.** Every AI call adds its estimated cost to `ai_spend_days`
   (one row per day, no tenant column, so checking the budget never reads other tenants'
   data). Once this month's total reaches `SIA_AI_MONTHLY_BUDGET_USD`, new AI work is refused
   (`503 ai_unavailable`, reason `budget_exhausted`), and the worker re-checks right before
   calling the model, so queued jobs can't overshoot it. The Anthropic console spend limit is
   the second, independent safety net.
6. **One availability answer for the UI:** usage endpoints report `available` and
   `unavailable_reason` (`not_configured`, `disabled_for_org`, `budget_exhausted`).

## Alternatives considered

- **Redis:** faster counters and sliding windows, but another service to run, secure and back
  up for a load PostgreSQL handles easily. Revisit with multiple servers or heavy traffic.
- **Rate limiting in Caddy:** needs a third-party Caddy module and can't see users or routes
  the way the app does.
- **A Procrastinate periodic cleanup job:** periodic tasks registered on the base app failed
  when the worker runs a connector-specific copy of it (the deferrer used the unopened app),
  which stopped the worker. Inline cleanup avoids the scheduler entirely.

## Consequences

- One extra small write per API request (sub-millisecond at this scale).
- Users behind one shared IP (an office) share limits; the limits are generous for that reason.
- The budget is an estimate from token counts and list prices; the invoice is authoritative.
