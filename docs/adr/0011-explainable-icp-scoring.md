# ADR-0011: Explainable rules-based ICP scoring

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

Sales teams need to know which companies to work first. Each organisation describes its ideal
customer profile (ICP) and every company gets a fit score. A score nobody can explain doesn't
get trusted, and data is often incomplete (not every company is enriched).

## Decision

1. **Rules, not a model.** The score is a weighted sum of up to six criteria (industry, size,
   country, business model, keywords, contacts on file), each with an importance of 1-5
   (worth 10-50 points) and an optional must-have flag. Score = earned / possible x 100;
   tiers A >= 75, B >= 50, C >= 25, D below. A partial match (an AI-estimated size range that only
   overlaps the ICP range) earns half the points. Failing a must-have makes the score 0.
2. **A pure engine.** `scoring/engine.py` is a function from (ICP, company facts) to (score,
   breakdown) with no database, network or randomness, so every rule is covered by unit
   tests. Every criterion produces one plain-language sentence, shown to users as the reason.
3. **Unknown counts as no match, but is labelled.** Missing data earns no points (a company we
   know nothing about must not look like a perfect fit) and is shown as "unknown - enrich to
   fill in", with data completeness reported separately. An unknown must-have does not
   disqualify.
4. **Only trustworthy inputs.** User-entered fields win; otherwise only *verified* AI facts
   (ADR-0010) are used. Keywords are searched in the description and verified facts, never in
   raw page text. Country spellings ("DE", "Germany", "Deutschland") are normalised to ISO codes.
5. **Storage.** One ICP per organisation (`icp_profiles`, JSON validated on every read and
   write, `version` incremented on each save). `company_scores` keeps each company's latest
   score, breakdown and the ICP version that produced it. The score is copied onto
   `companies.icp_score` with an index on `(organization_id, coalesce(icp_score, -1), id)` for
   keyset sorting; tier filters are score ranges on the same expression. Writing a score does
   not change the company's `updated_at`.
6. **When scores are recalculated.**
   - One company changes (edit, contact added/moved/removed, enrichment finished): rescored
     synchronously in the same transaction as the change, so a committed change always has a
     matching score.
   - Many companies change (ICP saved, CSV import): a background job rescores the organisation,
     enqueued in the same transaction as the change, at most one waiting job per organisation
     (queueing lock). The job reads the current ICP when it runs and commits per 1,000
     companies. Until it finishes, older scores are shown marked as out of date.
   - An admin can also trigger a full recalculation.

## Alternatives considered

- **Machine-learned scoring:** needs won/lost outcome data that new tenants don't have, and is
  hard to explain. Possible later, on top of this explainable baseline.
- **LLM judgement per company:** costly per rescore, non-deterministic, and harder to audit.
- **Periodic cross-tenant sweep:** a job reading every tenant's companies would need to bypass
  RLS. Event-driven rescoring inside the tenant's own transactions avoids that entirely.
- **Treating unknown as neutral (excluded from the total):** makes sparse records look like
  perfect fits; rejected.

## Consequences

- Scores are reproducible and auditable: the stored breakdown says exactly why.
- Measured (local, 50,000 companies in one tenant): full rescore 12 s in the background
  (dominated by writes); first page sorted by score with a tier filter 30 ms; an interactive
  preview over all companies 2.1 s. The preview should be revisited (sampling) if tenants grow
  far beyond that.
- Write paths for companies, contacts, imports and enrichment call the scoring module; any new
  write path that changes scored facts must do the same.
