/**
 * Simulated API for component tests (Mock Service Worker). Tests describe the responses they
 * need; any request without a handler fails the test, so nothing silently hits a real server.
 */
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import type { Schemas } from "@/lib/api/client";

// Default answers for endpoints most pages touch in passing; tests override them as needed.
const defaults = [
  http.get("*/api/enrichment/usage", () =>
    HttpResponse.json({
      used_today: 0,
      daily_limit: 200,
      remaining_today: 200,
      cost_today_usd: "0.0000",
      configured: true,
    }),
  ),
  http.get("*/api/companies/:id/enrichment", () =>
    HttpResponse.json({ latest_run: null, profile: null }),
  ),
];

export const server = setupServer(...defaults);

export const ORG = { id: "00000000-0000-4000-8000-000000000001", name: "Acme Sales" };

export function me(role: Schemas["Role"] = "owner"): Schemas["MeResponse"] {
  return {
    user: { id: "00000000-0000-4000-8000-0000000000aa", email: "dana@acme.test", name: "Dana" },
    active_organization: ORG,
    role,
    memberships: [{ organization: ORG, role }],
  };
}

export function company(overrides: Partial<Schemas["CompanyOut"]> = {}): Schemas["CompanyOut"] {
  return {
    id: crypto.randomUUID(),
    name: "Initech",
    domain: "initech.com",
    website: "https://initech.com/",
    industry: "Software",
    employee_count: 250,
    country: "US",
    city: null,
    description: null,
    attributes: {},
    source: "manual",
    created_at: "2026-11-01T10:00:00Z",
    updated_at: "2026-11-01T10:00:00Z",
    ...overrides,
  };
}

export const handlers = {
  loggedIn: (role: Schemas["Role"] = "owner") =>
    http.get("*/api/auth/me", () => HttpResponse.json(me(role))),
  loggedOut: () =>
    http.get("*/api/auth/me", () =>
      HttpResponse.json(
        { error: { code: "unauthenticated", message: "Authentication required." } },
        { status: 401 },
      ),
    ),
  facets: () =>
    http.get("*/api/companies/facets", () => HttpResponse.json({ industries: [], countries: [] })),
};
