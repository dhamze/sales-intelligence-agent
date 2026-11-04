# Product brief

## Problem

B2B sales reps spend hours researching accounts by hand and still guess which ones to work
first. Information is scattered across company websites, news, CRMs and spreadsheets, and
generic "AI research" tools produce confident summaries that cannot be verified.

## Ideal customer and users

- **Customer:** B2B companies with sales teams of 5–200 people.
- **Users:**
  - **SDR / BDR** — needs a prioritised daily list and a fast, trustworthy brief per account.
  - **Account Executive** — needs deeper account context before meetings.
  - **RevOps / Sales leader** — defines the ideal customer profile (ICP), imports lists,
    monitors coverage and quality.

## MVP promise

> Upload your account list → each company is enriched from public sources → scored against
> your ICP with an explainable breakdown → you get a grounded AI brief with cited sources and
> a suggested outreach angle.

## Product principles

1. **Explainable over magical.** Every score shows its breakdown; every AI claim links to a source.
2. **Grounded AI.** The model summarises evidence we collected; it does not invent facts.
3. **Tenant isolation is non-negotiable.** One customer can never see another's data.
4. **Respectful data collection.** Public company websites, user-provided data and licensed
   APIs only. No LinkedIn scraping. Minimal personal data (GDPR-aware).
5. **Cost-aware.** Every LLM call is metered; bulk work uses smaller models.

## MVP scope

| In | Out (roadmap) |
|---|---|
| CSV import with validation and de-duplication | CRM sync (HubSpot, Salesforce) |
| Website-based company enrichment | Paid enrichment providers |
| ICP definition + rule-based scoring | ML-trained scoring models |
| Cited AI account briefs and outreach angles | Automated email sending |
| Search, filter, sort | Natural-language / semantic search |
| Organisations, members, roles | SSO, billing, audit exports |

## Success metrics (for the demo)

- Time from CSV upload to a scored, enriched list: < 5 minutes for 100 companies.
- ≥ 90% of brief claims carry a valid source citation (measured by the eval harness).
- Zero cross-tenant data access in the automated security test suite.
