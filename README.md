# Sales Intelligence Agent

An AI-assisted sales intelligence platform for B2B sales teams: import an account list, enrich
each company from public sources, score it against your ideal customer profile with an
explainable breakdown, and get grounded AI account briefs with cited sources.

> **Status:** Phase 0 (foundation) — see the [roadmap](docs/architecture.md#roadmap).

## Documentation

- [Product brief](docs/product.md) — problem, users, MVP scope
- [Architecture](docs/architecture.md) — system design, technology choices, roadmap
- [Architecture Decision Records](docs/adr/) — why key decisions were made

## Tech stack

Python 3.13 · FastAPI · SQLAlchemy 2 · PostgreSQL 17 + pgvector · Procrastinate ·
React + TypeScript + Vite · Claude API · Docker · GitHub Actions

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package and project manager)
- Docker Desktop (PostgreSQL runs in a container from Phase 1)
- Node.js 22+ (frontend, from Phase 4)

## Getting started

```bash
# 1. Install Python 3.13 (if needed) and all locked dependencies into .venv
uv sync

# 2. Install the git hooks (lint, format, type check, secret scan on every commit)
uv run pre-commit install

# 3. Create your local configuration
cp .env.example .env   # then edit values
```

## Everyday commands

| Task | Command |
|---|---|
| Run tests | `uv run pytest` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Type check | `uv run mypy` |
| Run all pre-commit hooks | `uv run pre-commit run --all-files` |
| Add a backend dependency | `uv add --package sia-backend <name>` |
| Add a dev tool | `uv add --dev <name>` |

## Repository layout

```
backend/        FastAPI API + background worker (Python package `sia`)
docs/           Product brief, architecture, ADRs
.github/        CI workflows
pyproject.toml  uv workspace root and shared tool configuration
```
