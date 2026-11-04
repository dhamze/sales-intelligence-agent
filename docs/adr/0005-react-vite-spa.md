# ADR-0005: React + Vite SPA instead of Next.js

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

The frontend is an authenticated, data-heavy dashboard (tables, filters, detail views). Public
SEO pages are not part of the product.

## Decision

Use **React + TypeScript built with Vite**, with TanStack Router, TanStack Query and TanStack
Table, styled with Tailwind CSS and shadcn/ui components. The API client is generated from the
backend's OpenAPI schema.

## Consequences

- One backend (FastAPI) owns all business logic; the frontend is static files served by a CDN
  or any web server.
- Simpler mental model than Next.js server components and caching layers.
- If a public marketing site is needed later, it can be a separate project (or Next.js) without
  affecting the app.
