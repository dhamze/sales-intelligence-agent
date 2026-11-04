import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { Schemas } from "@/lib/api/client";
import { company, handlers, server } from "@/test/server";
import { renderApp } from "@/test/render";

const ID = "44444444-4444-4444-8444-444444444444";

function run(
  status: Schemas["RunStatus"],
  failure_reason: string | null = null,
): Schemas["EnrichmentRunOut"] {
  return {
    id: "55555555-5555-4555-8555-555555555555",
    company_id: ID,
    status,
    failure_reason,
    created_at: "2026-11-04T10:00:00Z",
    started_at: null,
    finished_at: status === "succeeded" || status === "failed" ? "2026-11-04T10:00:30Z" : null,
  };
}

const PROFILE: Schemas["CompanyProfileOut"] = {
  facts: {
    description: {
      value: "Workflow automation for finance teams",
      evidence: [{ source_url: "https://initech.com/", quote: "automation for finance teams" }],
    },
    headquarters_city: {
      value: "Berlin",
      evidence: [{ source_url: "https://initech.com/about", quote: "headquartered in Berlin" }],
    },
    products: [
      {
        value: "<img src=x onerror=alert(1)>",
        evidence: [{ source_url: "https://initech.com/", quote: "<b>Reconciliation</b> suite" }],
      },
    ],
  },
  sources: [{ url: "https://initech.com/" }, { url: "https://initech.com/about" }],
  facts_kept: 3,
  facts_dropped: 2,
  model: "claude-opus-5-5",
  generated_at: "2026-11-04T10:00:30Z",
};

type Enrichment = Schemas["CompanyEnrichmentOut"];

/** Simulate the API for the company page. */
function mockApi(enrichment: Enrichment, usage?: Record<string, unknown>): void {
  server.use(
    handlers.loggedIn(),
    http.get(`*/api/companies/${ID}`, () => HttpResponse.json(company({ id: ID }))),
    http.get("*/api/contacts", () => HttpResponse.json({ items: [], next_cursor: null })),
    http.get(`*/api/companies/${ID}/enrichment`, () => HttpResponse.json(enrichment)),
  );
  if (usage) {
    server.use(
      http.get("*/api/enrichment/usage", () =>
        HttpResponse.json({
          used_today: 3,
          daily_limit: 200,
          remaining_today: 197,
          cost_today_usd: "0.1500",
          configured: true,
          ...usage,
        }),
      ),
    );
  }
}

async function card() {
  const heading = await screen.findByText("AI profile");
  return heading.closest("div.rounded-xl") as HTMLElement;
}

describe("AI profile", () => {
  it("shows each verified fact with its quote and source link", async () => {
    mockApi({ latest_run: run("succeeded"), profile: PROFILE });
    renderApp(`/companies/${ID}`);
    const profile = within(await card());

    expect(await profile.findByText("Workflow automation for finance teams")).toBeInTheDocument();
    expect(profile.getByText(/headquartered in Berlin/)).toBeInTheDocument();
    const source = profile.getByRole("link", { name: /initech\.com\/about/ });
    expect(source).toHaveAttribute("href", "https://initech.com/about");
    expect(source).toHaveAttribute("rel", "noopener noreferrer");
    expect(profile.getByText(/2 unverifiable facts discarded/)).toBeInTheDocument();
    expect(profile.getByText("AI-extracted")).toBeInTheDocument();
  });

  it("renders text from websites and the model as text, never as HTML", async () => {
    mockApi({ latest_run: run("succeeded"), profile: PROFILE });
    renderApp(`/companies/${ID}`);
    const element = await card();

    expect(await within(element).findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(element.querySelector("img")).toBeNull();
    expect(element.querySelector("b")).toBeNull();
  });

  it("explains failures in plain language", async () => {
    mockApi({ latest_run: run("failed", "fetch_robots_disallowed"), profile: null });
    renderApp(`/companies/${ID}`);

    expect(
      await screen.findByText(/asks automated tools not to read it \(robots\.txt\)/),
    ).toBeInTheDocument();
  });

  it("starts enrichment and shows progress until the worker finishes", async () => {
    let state: Enrichment = { latest_run: null, profile: null };
    let posted = 0;
    mockApi(state);
    server.use(
      http.get(`*/api/companies/${ID}/enrichment`, () => HttpResponse.json(state)),
      http.post(`*/api/companies/${ID}/enrich`, () => {
        posted += 1;
        state = { latest_run: run("running"), profile: null };
        return HttpResponse.json(run("queued"), { status: 202 });
      }),
    );
    const { user } = renderApp(`/companies/${ID}`);
    const profile = within(await card());

    await user.click(await profile.findByRole("button", { name: "Enrich" }));

    expect(await profile.findByText(/Reading the website/)).toBeInTheDocument();
    expect(profile.getByRole("button", { name: /Enrich/ })).toBeDisabled();
    expect(posted).toBe(1);

    state = { latest_run: run("succeeded"), profile: PROFILE }; // the worker finished
    await waitFor(
      () => {
        expect(profile.getByText("Berlin")).toBeInTheDocument();
      },
      { timeout: 5000 },
    );
  });

  it("is disabled with an explanation when AI isn't configured", async () => {
    mockApi({ latest_run: null, profile: null }, { configured: false });
    renderApp(`/companies/${ID}`);
    const profile = within(await card());

    expect(await profile.findByText(/isn't configured on this server/)).toBeInTheDocument();
    expect(profile.getByRole("button", { name: "Enrich" })).toBeDisabled();
  });
});
