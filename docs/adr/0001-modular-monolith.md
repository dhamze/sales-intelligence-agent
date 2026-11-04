# ADR-0001: Modular monolith

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

The product has several distinct domains (identity, companies, imports, enrichment, scoring,
AI insights). It is built by a very small team and must remain cheap to run and easy to change.

## Decision

Build one backend deployable, organised into feature modules under `sia/modules/`, each owning
its tables and exposing a service interface. The API and the worker run from the same codebase
as two processes.

## Consequences

- One deploy, one database, simple local development and debugging.
- Module boundaries (enforced by convention and review) allow extracting a service later if a
  real scaling or ownership need appears.
- Risk: boundaries erode over time. Mitigation: module rules in `docs/architecture.md`; consider
  an import-linter check once several modules exist.
