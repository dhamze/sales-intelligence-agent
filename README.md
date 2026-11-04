# Sales Intelligence Agent

[![CI](https://github.com/dhamze/sales-intelligence-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/dhamze/sales-intelligence-agent/actions/workflows/ci.yml)

An AI-assisted sales intelligence platform for B2B sales teams: import an account list, enrich
each company from public sources, score it against your ideal customer profile with an
explainable breakdown, and get grounded AI account briefs with cited sources.

> **Status:** Phase 4 (web app) complete — see the [roadmap](docs/architecture.md#roadmap).

## Documentation

- [Product brief](docs/product.md) — problem, users, MVP scope
- [Architecture](docs/architecture.md) — system design, technology choices, roadmap
- [Architecture Decision Records](docs/adr/) — why key decisions were made

## Tech stack

Python 3.13 · FastAPI · SQLAlchemy 2 · PostgreSQL 17 + pgvector · Procrastinate ·
React + TypeScript + Vite · Claude API · Docker · GitHub Actions

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package and project manager)
- Docker Desktop
- Node.js 22+

## Getting started

Run all commands from the repository root.

```bash
# 1. Install Python 3.13 (if needed) and all locked dependencies into .venv
uv sync

# 2. Install the git hooks (lint, format, type check, secret scan on every commit)
uv run pre-commit install

# 3. Create your local configuration, then set a POSTGRES_PASSWORD of your choice
cp .env.example .env

# 4. Start PostgreSQL (first run also creates the sia_dev and sia_test databases)
docker compose up -d db

# 5. Apply database migrations
uv run alembic -c backend/alembic.ini upgrade head

# 6. Run the API with auto-reload
uv run uvicorn sia.main:create_app --factory --reload

# 7. In a second terminal: install and run the web app
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173> and create an account. The dev server forwards `/api/*` to the
backend, so the browser talks to a single origin and the session cookie works as in production.

Then open <http://127.0.0.1:8000/docs> for interactive API docs, or
<http://127.0.0.1:8000/health/ready> to confirm the database connection.

> Already had the database running before Phase 2? Create the restricted app role once:
> `docker compose up -d db` (picks up the new setting), then
> `docker compose exec db bash /docker-entrypoint-initdb.d/02-create-app-role.sh`

## Everyday commands

| Task | Command |
|---|---|
| Run all tests (needs the database running) | `uv run pytest` |
| Run unit tests only (no database) | `uv run pytest -m "not integration"` |
| Lint / format / type check | `uv run ruff check .` · `uv run ruff format .` · `uv run mypy` |
| Run all pre-commit hooks | `uv run pre-commit run --all-files` |
| Create a migration after changing models | `uv run alembic -c backend/alembic.ini revision --autogenerate -m "describe change"` |
| Apply / roll back one migration | `uv run alembic -c backend/alembic.ini upgrade head` · `... downgrade -1` |
| Seed demo companies into your org | `uv run python -m sia.scripts.seed_companies --email you@example.com --count 50000` |
| Stop the database (keeps data) | `docker compose stop` |
| Delete all local database data | `docker compose down -v` |
| Add a backend dependency | `uv add --package sia-backend <name>` |
| Add a dev tool | `uv add --dev <name>` |
| Frontend: type check / lint / unit tests | `npm run typecheck` · `npm run lint` · `npm test` (in `frontend/`) |
| Regenerate frontend API types after backend changes | `npm run api:sync` (in `frontend/`) |
| End-to-end tests (real browser + API + DB) | `npm run build && npm run e2e` (in `frontend/`, database running) |

## Repository layout

```
backend/
  src/sia/
    main.py         App factory
    core/           Config, logging, database, errors, request middleware
    modules/
      health/       Liveness and readiness probes
      identity/     Users, organisations, memberships, sessions, auth API
      companies/    Companies (accounts), domain normalisation, search
      contacts/     Contacts linked to companies
      imports/      CSV import: parse, map, preview, merge
    scripts/        Developer scripts (seed data)
  migrations/       Alembic database migrations
  tests/unit/       Fast tests, no database
  tests/integration/  Tests against a real PostgreSQL
frontend/
  src/routes/       Pages (file-based routing)
  src/features/     Feature code (auth, shell, companies, ...)
  src/components/   Shared UI components
  src/lib/api/      Typed API client generated from the backend's OpenAPI schema
infra/postgres/     Database init scripts
docs/               Product brief, architecture, ADRs
compose.yaml        Local infrastructure (PostgreSQL + pgvector)
pyproject.toml      uv workspace root and shared tool configuration
```

## Security model (summary)

- The API connects as `sia_app`, a database role that cannot bypass Row-Level Security; tenant
  isolation is enforced by PostgreSQL itself ([ADR-0007](docs/adr/0007-database-roles-and-rls-mechanics.md)).
- Passwords: Argon2id. Sessions: random 256-bit tokens in `HttpOnly`, `SameSite=Lax` cookies,
  stored only as SHA-256 hashes, revocable, idle and absolute expiry.
- CSRF: `Origin` header check on state-changing requests. Brute force: per-email and per-IP
  login throttling. Security events are logged by ID, never with passwords or emails.

## Troubleshooting

- **Slow database connections on Windows:** use `POSTGRES_HOST=127.0.0.1`, not `localhost`.
  Windows tries IPv6 (`::1`) first, which Docker does not listen on, adding ~2 s per connection.
- **`docker` not found:** open a new terminal after installing Docker Desktop.
