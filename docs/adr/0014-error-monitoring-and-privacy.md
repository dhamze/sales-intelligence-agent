# ADR-0014: Error monitoring with Sentry, privacy first

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

In production nobody watches the logs. Crashes in API requests, failed background jobs and
browser errors must reach the operator quickly. The app holds customer data (company lists,
contacts, website text, AI prompts), so whatever monitoring sees must be limited deliberately.

## Decision

1. **Sentry (free tier) for the API, the worker and the browser**, enabled only when a DSN is
   configured (`SENTRY_DSN` at runtime; `VITE_SENTRY_DSN` at build time for the browser).
2. **Errors come from the logs we already write.** A structlog processor forwards every
   ERROR/CRITICAL event (with traceback when present) using the event name as the message and
   the structured context as extra data. Crashing requests and crashing jobs are already logged
   at that level, so no call sites change. Lower levels become breadcrumbs only.
3. **Data minimisation, enforced twice.** The SDKs' `data_collection` options turn off user
   identity, cookies, request bodies, query strings, AI prompts/responses (the SDK instruments
   the Anthropic client automatically), database query data and stack-frame variables, and
   allow only harmless request headers. `scrub_event` / `filterEvent` then remove the same
   categories again, and filter any context key that looks personal or secret. The browser
   drops console breadcrumbs and strips query strings from URLs; expected 4xx API errors are
   not reported.
4. **CSP stays strict:** `connect-src` allows only our origin and Sentry's ingest hosts.
5. **No performance tracing by default** (`SIA_SENTRY_TRACES_SAMPLE_RATE=0`): errors only, which
   fits the free tier and sends the least data.

## Alternatives considered

- **Logs only:** no alerting, and errors are noticed when users complain.
- **Self-hosted error tracking (GlitchTip, Sentry self-hosted):** keeps data in-house but needs
  far more memory than the demo server has.
- **A tunnel endpoint for browser events:** hides Sentry from ad blockers and keeps CSP at
  `'self'`, but adds a public endpoint that must not become an open relay. Not worth it yet.

## Consequences

- Error reports contain stack traces and event names, not customer content. Diagnosing an issue
  may require the server logs (via the request ID tag) for the details.
- Verified: a browser error on a page with a search query in the URL was reported without the
  query or session cookie (local production stack, report intercepted, nothing sent out).
