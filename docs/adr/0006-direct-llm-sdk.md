# ADR-0006: Direct LLM SDK instead of an orchestration framework

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

The product uses LLMs for structured extraction (enrichment) and grounded generation (account
briefs). Frameworks such as LangChain or LlamaIndex add abstractions over these calls.

## Decision

Call Claude through the **official Anthropic Python SDK**, wrapped in a small internal
`LLMClient` interface in `sia/ai/`.

- Outputs are validated against Pydantic schemas.
- Prompts live in code, are versioned, and every call records model, prompt version, token
  usage and cost in the database.
- Tests use a deterministic fake `LLMClient`; a separate eval suite runs real calls against a
  golden dataset.
- Planned models: a small, fast model for bulk extraction and a stronger model for briefs.

## Consequences

- Full control and visibility over prompts, retries and costs; fewer dependencies.
- We write a little more glue code (retry policy, output parsing) ourselves.
- Switching or adding a provider means implementing one interface.
