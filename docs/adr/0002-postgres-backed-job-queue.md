# ADR-0002: Postgres-backed job queue (Procrastinate)

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

Enrichment (fetching websites) and AI generation are slow and can fail, so they must run
outside HTTP requests, with retries. Common options: Celery + Redis, arq/Taskiq + Redis, or a
queue stored in PostgreSQL.

## Decision

Use **Procrastinate**, an async-native job queue that stores jobs in PostgreSQL.

## Consequences

- No Redis or broker to run, secure and back up for the MVP.
- Jobs can be enqueued **in the same transaction** as the data they process — if the import
  commit fails, no orphan job exists; if it succeeds, the job is guaranteed to exist.
- Async-native, matching the async FastAPI/SQLAlchemy stack (Celery is sync-first).
- Throughput is lower than a dedicated broker; ample for the expected volume (thousands of jobs
  per hour). If this becomes a bottleneck, job functions are thin wrappers around services, so
  moving to Celery/Redis is contained.
