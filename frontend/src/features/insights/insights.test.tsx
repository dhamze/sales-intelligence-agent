import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { Schemas } from "@/lib/api/client";
import { company, handlers, server } from "@/test/server";
import { renderApp } from "@/test/render";

const ID = "77777777-7777-4777-8777-777777777777";

function run(
  status: Schemas["RunStatus"],
  failure_reason: string | null = null,
): Schemas["BriefRunOut"] {
  return {
    id: "88888888-8888-4888-8888-888888888888",
    company_id: ID,
    status,
    failure_reason,
    created_at: "2026-11-04T10:00:00Z",
    started_at: null,
    finished_at: null,
  };
}

const cite = (source_id: string, quote: string) => [{ source_id, quote }];

const BRIEF: Schemas["BriefOut"] = {
  summary: [
    {
      text: "Initech automates accounts payable for manufacturers.",
      citations: cite("W1", "automates accounts payable"),
    },
  ],
  fit: [{ text: "Strong fit on industry.", citations: cite("S", "Fintech is in your ICP") }],
  key_facts: [
    { text: "<img src=x onerror=alert(1)>", citations: cite("W2", "hiring 12 engineers") },
  ],
  priorities: [
    { text: "They likely want faster month-end close.", citations: cite("W1", "close faster") },
  ],
  outreach: {
    angle: "Lead with month-end close speed.",
    opening_line: "Saw you're hiring for the treasury module.",
    discovery_questions: ["How long does month-end take today?"],
    citations: cite("W2", "hiring 12 engineers"),
  },
  gaps: ["Budget is not stated."],
  sources: [
    { id: "W1", kind: "website", title: "Initech", url: "https://initech.com/" },
    { id: "W2", kind: "website", title: "Careers", url: "https://initech.com/careers" },
    { id: "R", kind: "record", title: "Company record (your CRM data)", url: null },
    { id: "S", kind: "score", title: "ICP fit (your ideal customer profile)", url: null },
  ],
  claims_kept: 5,
  claims_dropped: 2,
  model: "claude-opus-5-5",
  generated_at: "2026-11-04T10:00:30Z",
  stale: false,
};

function companyPage(brief: Schemas["CompanyBriefOut"]) {
  server.use(
    handlers.loggedIn(),
    http.get(`*/api/companies/${ID}`, () => HttpResponse.json(company({ id: ID }))),
    http.get("*/api/contacts", () => HttpResponse.json({ items: [], next_cursor: null })),
    http.get(`*/api/companies/${ID}/brief`, () => HttpResponse.json(brief)),
  );
}

async function card() {
  const heading = await screen.findByText("Account brief");
  return within(heading.closest("div.rounded-xl") as HTMLElement);
}

describe("Account brief", () => {
  it("shows every section with citations that open their quote and source", async () => {
    companyPage({ latest_run: run("succeeded"), brief: BRIEF });
    const { user } = renderApp(`/companies/${ID}`);
    const brief = await card();

    expect(
      await brief.findByText(/Initech automates accounts payable for manufacturers/),
    ).toBeInTheDocument();
    expect(brief.getByRole("list", { name: "Why they fit" })).toBeInTheDocument();
    expect(brief.getByText(/AI inference, based on the cited facts/)).toBeInTheDocument();
    expect(brief.getByText("Budget is not stated.")).toBeInTheDocument();
    expect(brief.getByText(/2 unverifiable claims removed/)).toBeInTheDocument();

    const facts = within(brief.getByRole("list", { name: "Key facts" }));
    await user.click(facts.getByRole("button", { name: "Source W2: show quote" }));
    const popover = await screen.findByRole("dialog");
    expect(within(popover).getByText(/hiring 12 engineers/)).toBeInTheDocument();
    expect(within(popover).getByRole("link", { name: /Open page/ })).toHaveAttribute(
      "href",
      "https://initech.com/careers",
    );
    expect(within(popover).getByRole("link", { name: /Open page/ })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
  });

  it("renders AI text as text, never as HTML", async () => {
    companyPage({ latest_run: run("succeeded"), brief: BRIEF });
    renderApp(`/companies/${ID}`);
    const heading = await screen.findByText("Account brief");
    const element = heading.closest("div.rounded-xl") as HTMLElement;

    expect(await within(element).findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(element.querySelector("img")).toBeNull();
  });

  it("copies the opening line and questions", async () => {
    companyPage({ latest_run: run("succeeded"), brief: BRIEF });
    const { user } = renderApp(`/companies/${ID}`);
    const outreach = within(await screen.findByRole("region", { name: "Outreach angle" }));

    await user.click(outreach.getByRole("button", { name: "Copy" }));

    expect(await navigator.clipboard.readText()).toBe(
      "Saw you're hiring for the treasury module.\n\n- How long does month-end take today?",
    );
  });

  it("says when the brief is out of date", async () => {
    companyPage({ latest_run: run("succeeded"), brief: { ...BRIEF, stale: true } });
    renderApp(`/companies/${ID}`);
    const brief = await card();

    expect(await brief.findByText(/changed after the brief was written/)).toBeInTheDocument();
    expect(brief.getByRole("button", { name: "Regenerate" })).toBeEnabled();
  });

  it("generates a brief and shows progress until the worker finishes", async () => {
    let state: Schemas["CompanyBriefOut"] = { latest_run: null, brief: null };
    let posted = 0;
    companyPage(state);
    server.use(
      http.get(`*/api/companies/${ID}/brief`, () => HttpResponse.json(state)),
      http.post(`*/api/companies/${ID}/brief`, () => {
        posted += 1;
        state = { latest_run: run("running"), brief: null };
        return HttpResponse.json(run("queued"), { status: 202 });
      }),
    );
    const { user } = renderApp(`/companies/${ID}`);
    const brief = await card();

    await user.click(await brief.findByRole("button", { name: "Generate brief" }));

    expect(await brief.findByText(/checking every citation/)).toBeInTheDocument();
    expect(posted).toBe(1);
    state = { latest_run: run("succeeded"), brief: BRIEF };
    await waitFor(
      () => {
        expect(brief.getByText(/Lead with month-end close speed/)).toBeInTheDocument();
      },
      { timeout: 5000 },
    );
  });

  it("explains the daily limit and failed runs in plain language", async () => {
    companyPage({ latest_run: run("failed", "llm_refused"), brief: null });
    server.use(
      http.post(`*/api/companies/${ID}/brief`, () =>
        HttpResponse.json(
          { error: { code: "brief_daily_limit", message: "limit" } },
          { status: 429 },
        ),
      ),
    );
    const { user } = renderApp(`/companies/${ID}`);
    const brief = await card();

    expect(await brief.findByText(/declined to write this brief/)).toBeInTheDocument();
    await user.click(brief.getByRole("button", { name: "Generate brief" }));
    expect(await screen.findByText(/Today's brief limit has been reached/)).toBeInTheDocument();
  });
});

describe("AI usage (settings)", () => {
  it("shows spend today, this month and by feature", async () => {
    server.use(
      handlers.loggedIn(),
      handlers.facets(),
      http.get("*/api/organizations/current/members", () => HttpResponse.json([])),
      http.get("*/api/ai/usage", () =>
        HttpResponse.json({
          cost_today_usd: "0.1800",
          cost_month_usd: "2.4567",
          month_by_purpose: [
            { purpose: "account_brief", calls: 20, cost_usd: "1.8000" },
            { purpose: "company_profile", calls: 31, cost_usd: "0.6567" },
          ],
          briefs_today: 2,
          brief_daily_limit: 50,
          configured: true,
        }),
      ),
    );
    renderApp("/settings");

    const heading = await screen.findByText("AI usage");
    const usage = within(heading.closest("div.rounded-xl") as HTMLElement);
    expect(await usage.findByText("$2.46")).toBeInTheDocument();
    expect(usage.getByText("2 / 50")).toBeInTheDocument();
    const table = within(usage.getByRole("table", { name: "This month by feature" }));
    expect(table.getByText("Account briefs")).toBeInTheDocument();
    expect(table.getByText("Website enrichment")).toBeInTheDocument();
    expect(table.getByText("$1.80")).toBeInTheDocument();
  });
});
