# Architecture Decision Records

An ADR captures one significant technical decision: the context, the choice, and its
consequences. ADRs are never edited after acceptance — a changed decision gets a new ADR that
supersedes the old one.

| # | Decision | Status |
|---|---|---|
| [0001](0001-modular-monolith.md) | Modular monolith | Accepted |
| [0002](0002-postgres-backed-job-queue.md) | Postgres-backed job queue (Procrastinate) | Accepted |
| [0003](0003-first-party-session-auth.md) | First-party session authentication | Accepted |
| [0004](0004-multi-tenancy-rls.md) | Shared-schema multi-tenancy with Row-Level Security | Accepted |
| [0005](0005-react-vite-spa.md) | React + Vite SPA instead of Next.js | Accepted |
| [0006](0006-direct-llm-sdk.md) | Direct LLM SDK instead of an orchestration framework | Accepted |
| [0007](0007-database-roles-and-rls-mechanics.md) | Database roles and Row-Level Security mechanics | Accepted |
| [0008](0008-fuzzy-search-under-rls.md) | Fuzzy search under Row-Level Security | Accepted |
| [0009](0009-ssrf-safe-fetching.md) | SSRF-safe fetching of user-supplied websites | Accepted |
| [0010](0010-grounded-extraction.md) | Grounded AI extraction with verified evidence | Accepted |
| [0011](0011-explainable-icp-scoring.md) | Explainable rules-based ICP scoring | Accepted |
| [0012](0012-cited-account-briefs.md) | Cited account briefs and how they are evaluated | Accepted |
| [0013](0013-abuse-and-cost-protection.md) | Abuse and cost protection for a public deployment | Accepted |
| [0014](0014-error-monitoring-and-privacy.md) | Error monitoring with Sentry, privacy first | Accepted |
