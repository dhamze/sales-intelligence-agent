# Architecture

> Status: approved 2026-11-04. Significant changes are recorded as ADRs in [`adr/`](adr/).

## Overview

The Sales Intelligence Agent is a **modular monolith**: a single backend codebase split into
feature modules with strict boundaries, a separate single-page frontend, one PostgreSQL
database, and a background worker for slow or unreliable work (web fetching, LLM calls).

```
 React SPA ──HTTPS/JSON──▶ FastAPI API ──▶ PostgreSQL (+pgvector, RLS)
 (typed client generated       │                 ▲
  from OpenAPI)                │ enqueue job     │ same DB (job queue lives here too)
                               ▼                 │
                          Worker process ──▶ Claude API, company websites,
                          (enrichment, AI)       CRM / news APIs (later)
```

## Technology choices

| Concern | Choice | Rationale |
|---|---|---|
| Backend API | FastAPI + Pydantic v2, Python 3.13 | Typed validation, automatic OpenAPI, async I/O for LLM and web calls. |
| ORM / migrations | SQLAlchemy 2.0 (async) + Alembic | Industry standard; every schema change is a reviewed, versioned migration. |
| Database | PostgreSQL 17 + pgvector | Relational data, full-text search (`pg_trgm`), JSONB and vectors in one system. |
| Background jobs | Procrastinate (Postgres-backed) | No extra infrastructure; jobs enqueued transactionally with the data they act on. See [ADR-0002](adr/0002-postgres-backed-job-queue.md). |
| Cache / rate limiting | Redis — **deferred to Phase 8** | Not required by MVP features. |
| Frontend | React + TypeScript + Vite, TanStack Query/Table/Router, Tailwind + shadcn/ui | Authenticated dashboard app; SSR adds little. See [ADR-0005](adr/0005-react-vite-spa.md). |
| API contract | TypeScript client generated from OpenAPI | Backend changes that break the frontend fail at compile time. |
| AI | Official Anthropic SDK behind an internal `LLMClient` interface | Structured outputs, versioned prompts, per-call cost logging, offline fakes for tests. See [ADR-0006](adr/0006-direct-llm-sdk.md). |
| Auth | First-party session auth (Argon2, HTTP-only cookies, Postgres sessions) | See [ADR-0003](adr/0003-first-party-session-auth.md). |
| Multi-tenancy | `organization_id` on tenant tables + Postgres Row-Level Security | Defense in depth. See [ADR-0004](adr/0004-multi-tenancy-rls.md). |
| Logging | structlog (JSON in prod) with request and org IDs; Sentry/OpenTelemetry later | Searchable, correlated logs. |
| Testing / quality | pytest on real Postgres, ruff, mypy strict, Vitest, Playwright, pre-commit, GitHub Actions | |
| Packaging | uv workspace (`uv.lock`), npm for frontend | Reproducible across machines, CI and Docker. |
| Deployment | Multi-stage Docker images; PaaS + managed Postgres for the demo | Portable to AWS ECS/RDS later. |

## Repository layout

```
sales-intelligence-agent/
├── backend/
│   ├── pyproject.toml, alembic.ini, Dockerfile
│   ├── migrations/
│   ├── src/sia/
│   │   ├── main.py              # app factory
│   │   ├── core/                # config, db, logging, errors, security, tenancy
│   │   ├── ai/                  # LLM client, prompts/, output schemas
│   │   ├── modules/             # each: router, service, repository, models, schemas
│   │   │   ├── identity/        # users, orgs, memberships, sessions
│   │   │   ├── companies/  contacts/  imports/
│   │   │   ├── enrichment/  scoring/  insights/
│   │   └── worker/              # job registration
│   └── tests/  (unit/, integration/, evals/)
├── frontend/   src/ (routes/, features/, components/, lib/api/)
├── infra/      postgres init scripts
├── docs/       architecture.md, product.md, adr/
├── .github/workflows/
├── compose.yaml, .env.example
├── pyproject.toml, uv.lock     # uv workspace root + shared tooling config
└── README.md
```

### Module rules

1. A module owns its tables. Other modules use its **service** functions, never its models or
   repositories directly.
2. Routers are thin: parse input, call a service, return a schema.
3. Services hold business logic and never touch HTTP concepts.
4. Repositories are the only place that builds SQL queries, and always scope by tenant.

## Database and Docker strategy

- `compose.yaml` runs `db` (`pgvector/pgvector:pg17`, healthcheck, named volume) by default.
  `api`, `worker` and `frontend` containers are behind the `full` profile for parity checks.
- Day-to-day development: Postgres in Docker; API and frontend run natively on Windows (fast
  hot reload — bind-mount file watching from NTFS into Linux containers is slow).
- Separate `sia_dev` and `sia_test` databases. Schema changes only via Alembic.
- Secrets only in `.env` (git-ignored); every variable documented in `.env.example`.

## Roadmap

| Phase | Scope | Outcome |
|---|---|---|
| 0. Foundation | Repo hygiene, uv workspace, pre-commit, CI, docs | Clean, protected repo |
| 1. Backend skeleton | App factory, config, logging, errors, health, Postgres, Alembic, test harness | `/health` checks DB; CI green |
| 2. Identity & tenancy | Users, orgs, roles, sessions, RLS, cross-tenant leak tests | Secure multi-tenant base |
| 3. Core data | Companies/contacts API, CSV import with validation + dedupe, search/filter/pagination | Import and search 1,000 companies |
| 4. Frontend MVP | Login, company table, detail, import UI, generated client | Usable product |
| 5. Jobs + enrichment | Worker, safe fetcher (robots.txt, timeouts, SSRF protection), LLM extraction with sources | Companies auto-enrich |
| 6. Scoring | ICP builder, explainable rule-based score, re-scoring jobs | Prioritised list |
| 7. AI insights | Cited account briefs, outreach angles, eval harness, cost tracking | **MVP complete** |
| 8. Production | Deploy, Sentry/OTel, rate limiting (Redis), backups, security review | Public demo |
| Later | CRM sync, buying signals, semantic/NL search, reporting, alerts, SSO, billing | Growth |
