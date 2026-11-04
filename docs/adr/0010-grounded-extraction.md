# ADR-0010: Grounded AI extraction with verified evidence

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

Enrichment asks a language model to describe a company from its website. Models can state
plausible facts that the source never said (hallucination), and website text is untrusted input
that may try to steer the model (prompt injection). Sales teams act on this data, so wrong facts
presented confidently are worse than missing ones.

## Decision

1. **Every fact carries evidence.** The structured-output schema requires, for each fact, a
   verbatim quote and the URL of the page it was copied from. The API guarantees the response
   matches the schema; we validate it into Pydantic models ourselves (so truncated or invalid
   output is classified, and its token usage still logged).
2. **Evidence is verified mechanically.** After extraction, each quote must occur in the text we
   fetched from the cited page (comparison ignores case, spacing, quote and dash styles; quotes
   under 8 characters don't count). Unverified evidence is removed; a fact with no remaining
   evidence is dropped and counted (`facts_dropped`). Invented facts cannot pass this check.
3. **Untrusted input stays data.** Page text is XML-escaped inside delimited blocks, the system
   prompt says it is data not instructions, and the model has no tools. Injection can at most
   change which *true* statements from the page are selected.
4. **People's data wins.** Verified values fill only empty company fields; the full profile is
   stored separately with its sources and shown labelled as AI-extracted.
5. **Every call is accounted for.** Model, prompt version, tokens, estimated cost, latency, stop
   reason and request ID are logged per call, including refusals and failures. Per-organisation
   daily caps bound spend.
6. **Model choice is measured, not assumed.** An opt-in live evaluation (10 real company sites +
   an injection page, same fetched text for every model) compares accuracy, verified-fact rate,
   cost and latency. Default `claude-opus-5-5` with effort `low`; configurable via settings.
   Claude Opus 5.5 requests opt into server-side refusal fallback (`fallbacks: "default"`).

## Consequences

- Facts phrased only implicitly on a site may be dropped (false negatives) - preferred over
  false positives.
- The stored page text doubles as the grounding corpus for AI briefs (Phase 7).
- Prompt or schema changes bump `PROMPT_VERSION`, so logged results stay comparable.
