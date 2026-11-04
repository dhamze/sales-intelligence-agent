import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { Schemas } from "@/lib/api/client";
import { company, handlers, server } from "@/test/server";
import { renderApp } from "@/test/render";

import { toDefinition } from "./icp-builder";

const ID = "66666666-6666-4666-8666-666666666666";

const ICP: Schemas["ICPOut"] = {
  definition: {
    criteria: [{ kind: "industry", industries: ["Software"], importance: 5, must_have: false }],
  },
  version: 3,
  updated_at: "2026-11-04T10:00:00Z",
  status: { total_companies: 120, scored_current: 120 },
};

const PREVIEW: Schemas["ICPPreview"] = {
  total_companies: 200,
  tiers: { A: 50, B: 30, C: 20, D: 100 },
  top: [{ company_id: ID, name: "Initech", score: 100, tier: "A" }],
  average_completeness: 0.8,
};

function settingsApi(role: Schemas["Role"] = "owner") {
  server.use(
    handlers.loggedIn(role),
    handlers.facets(),
    http.get("*/api/organizations/current/members", () => HttpResponse.json([])),
  );
}

function card() {
  return screen.findByRole("heading", { name: "Ideal customer profile" }).then((heading) => {
    const element = heading.closest("#icp");
    if (!(element instanceof HTMLElement)) throw new Error("ICP card not found");
    return within(element);
  });
}

describe("toDefinition", () => {
  const base = toDefinition; // the form's own validation, mirroring the API's

  it("requires at least one criterion", () => {
    const { definition, errors } = base(draftWith({}));
    expect(definition).toBeUndefined();
    expect(errors.form).toMatch(/at least one criterion/);
  });

  it("validates size bounds", () => {
    const { errors } = base(draftWith({ size: { enabled: true, min: "500", max: "50" } }));
    expect(errors.size).toBe("The minimum is larger than the maximum.");
    expect(base(draftWith({ size: { enabled: true, min: "abc" } })).errors.size).toMatch(/whole/);
    expect(base(draftWith({ size: { enabled: true } })).errors.size).toMatch(/minimum or/);
  });

  it("builds the API body from enabled criteria only", () => {
    const { definition } = base(
      draftWith({
        size: { enabled: true, min: "50", max: "", importance: 4, must_have: true },
        keywords: { enabled: false, keywords: ["ignored"] },
      }),
    );
    expect(definition).toEqual({
      criteria: [
        { kind: "size", importance: 4, must_have: true, min_employees: 50, max_employees: null },
      ],
    });
  });
});

describe("ICP builder (settings)", () => {
  it("previews the tiers live and saves the profile", async () => {
    settingsApi();
    let saved: unknown;
    const previews: unknown[] = [];
    server.use(
      http.post("*/api/icp/preview", async ({ request }) => {
        previews.push(await request.json());
        return HttpResponse.json(PREVIEW);
      }),
      http.put("*/api/icp", async ({ request }) => {
        saved = await request.json();
        return HttpResponse.json({
          ...ICP,
          version: 1,
          definition: saved,
          status: { total_companies: 200, scored_current: 0 },
        });
      }),
    );
    const { user } = renderApp("/settings");
    const icp = await card();

    expect(await icp.findByText(/Turn on a criterion/)).toBeInTheDocument();
    await user.click(await icp.findByRole("checkbox", { name: /^Industry/ }));
    await user.type(icp.getByLabelText("Add industries"), "Software{Enter}");

    const top = await icp.findByRole("list", { name: "Best fits" });
    expect(within(top).getByText("Initech")).toBeInTheDocument();
    expect(icp.getByText("(50%)")).toBeInTheDocument(); // D: 100 of 200
    expect(previews).toHaveLength(1); // debounced: one preview, not one per keystroke

    await user.click(icp.getByRole("button", { name: "Save ICP" }));

    await waitFor(() => {
      expect(saved).toEqual({
        criteria: [{ kind: "industry", importance: 3, must_have: false, industries: ["Software"] }],
      });
    });
    expect(await screen.findByText(/Rescoring 200 companies/)).toBeInTheDocument();
  });

  it("has nothing to save until the saved profile is changed", async () => {
    settingsApi();
    server.use(
      http.post("*/api/icp/preview", () => HttpResponse.json(PREVIEW)),
      // The API lists fields in its own order; that must not count as a change.
      http.get("*/api/icp", () =>
        HttpResponse.json({
          ...ICP,
          definition: {
            criteria: [
              { importance: 5, must_have: false, industries: ["Software"], kind: "industry" },
            ],
          },
        }),
      ),
    );
    const { user } = renderApp("/settings");
    const icp = await card();

    const save = await icp.findByRole("button", { name: "Save changes" });
    expect(save).toBeDisabled();
    expect(icp.queryByRole("button", { name: "Discard changes" })).not.toBeInTheDocument();

    await user.click(icp.getByRole("button", { name: "Remove Software" }));
    await user.type(icp.getByLabelText("Add industries"), "Fintech{Enter}");
    expect(save).toBeEnabled();
    await user.click(icp.getByRole("button", { name: "Discard changes" }));
    expect(save).toBeDisabled();
  });

  it("shows validation problems instead of saving", async () => {
    settingsApi();
    let puts = 0;
    server.use(
      http.put("*/api/icp", () => {
        puts += 1;
        return HttpResponse.json(ICP);
      }),
    );
    const { user } = renderApp("/settings");
    const icp = await card();

    await user.click(await icp.findByRole("checkbox", { name: /^Country/ }));
    await user.click(icp.getByRole("button", { name: "Save ICP" }));

    expect(await icp.findByText("Add at least one country.")).toBeInTheDocument();
    expect(puts).toBe(0);
  });

  it("is read-only for members and shows progress while rescoring", async () => {
    settingsApi("member");
    server.use(
      http.get("*/api/icp", () =>
        HttpResponse.json({ ...ICP, status: { total_companies: 120, scored_current: 40 } }),
      ),
    );
    renderApp("/settings");
    const icp = await card();

    expect(await icp.findByText(/Only admins can change it/)).toBeInTheDocument();
    expect(await icp.findByRole("checkbox", { name: /^Industry/ })).toBeDisabled();
    expect(icp.queryByRole("button", { name: /Save/ })).not.toBeInTheDocument();
    expect(icp.getByText(/Recalculating scores… 40 of 120 companies done/)).toBeInTheDocument();
  });
});

describe("Companies list with scoring", () => {
  it("shows the fit, sorts best-first and filters by tier", async () => {
    const requests: URL[] = [];
    server.use(
      handlers.loggedIn(),
      handlers.facets(),
      http.get("*/api/icp", () => HttpResponse.json(ICP)),
      http.get("*/api/companies", ({ request }) => {
        requests.push(new URL(request.url));
        return HttpResponse.json({
          items: [
            company({ name: "Initech", icp_score: 86, icp_tier: "A" }),
            company({ name: "Globex", icp_score: null, icp_tier: null }),
          ],
          next_cursor: null,
        });
      }),
    );
    const { user, router } = renderApp("/companies");

    const row = (await screen.findByRole("link", { name: "Initech" })).closest("tr");
    expect(within(row as HTMLElement).getByLabelText("Tier A")).toBeInTheDocument();
    expect(screen.getByText("Not scored")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "ICP fit" }));
    await waitFor(() => {
      expect(requests.at(-1)?.searchParams.get("sort")).toBe("-icp_score");
    });

    await user.click(screen.getByRole("button", { name: /ICP tier/ }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: /Excellent fit/ }));
    await waitFor(() => {
      expect(requests.at(-1)?.searchParams.getAll("tier")).toEqual(["A"]);
    });
    expect(router.state.location.search).toMatchObject({ sort: "-icp_score", tier: ["A"] });
  });

  it("invites the team to set up scoring when there's no ICP", async () => {
    server.use(
      handlers.loggedIn(),
      handlers.facets(),
      http.get("*/api/companies", () =>
        HttpResponse.json({ items: [company()], next_cursor: null }),
      ),
    );
    renderApp("/companies");

    expect(await screen.findByRole("link", { name: "Set up ICP scoring" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ICP fit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ICP tier/ })).not.toBeInTheDocument();
  });
});

describe("ICP fit card (company page)", () => {
  function companyPage(score: Schemas["CompanyScoreOut"] | null, icp = ICP) {
    server.use(
      handlers.loggedIn(),
      http.get(`*/api/companies/${ID}`, () =>
        HttpResponse.json(company({ id: ID, icp_score: score?.score ?? null })),
      ),
      http.get("*/api/contacts", () => HttpResponse.json({ items: [], next_cursor: null })),
      http.get("*/api/icp", () => HttpResponse.json(icp)),
      http.get(`*/api/companies/${ID}/score`, () => HttpResponse.json(score)),
    );
  }

  const SCORE: Schemas["CompanyScoreOut"] = {
    score: 63,
    tier: "B",
    disqualified: false,
    completeness: 0.67,
    icp_version: 3,
    current: true,
    scored_at: "2026-11-04T10:00:00Z",
    breakdown: [
      {
        kind: "industry",
        status: "match",
        points: 50,
        max_points: 50,
        must_have: true,
        detail: "Software is in your ICP (Software)",
      },
      {
        kind: "size",
        status: "partial",
        points: 15,
        max_points: 30,
        must_have: false,
        detail: "11-50 employees (from website) partly overlaps your ICP (50-500)",
      },
      {
        kind: "country",
        status: "unknown",
        points: 0,
        max_points: 20,
        must_have: false,
        detail: "Country unknown (enrich to fill in)",
      },
    ],
  };

  it("explains the score criterion by criterion", async () => {
    companyPage(SCORE);
    renderApp(`/companies/${ID}`);

    const breakdown = await screen.findByRole("list", { name: "Score breakdown" });
    const [industry, size, country, ...rest] = within(breakdown)
      .getAllByRole("listitem")
      .map((item) => within(item));
    expect(rest).toHaveLength(0);
    expect(industry?.getByLabelText("Match")).toBeInTheDocument();
    expect(industry?.getByText("Must-have")).toBeInTheDocument();
    expect(size?.getByText("15 / 30 pts")).toBeInTheDocument();
    expect(country?.getByText("Country unknown (enrich to fill in)")).toBeInTheDocument();
    expect(screen.getByText(/Data completeness 67%/)).toBeInTheDocument();
    expect(screen.getByText(/1 criterion unknown, counted as no match/)).toBeInTheDocument();
  });

  it("says when a score is being recalculated", async () => {
    companyPage({ ...SCORE, current: false, icp_version: 2 });
    renderApp(`/companies/${ID}`);

    expect(await screen.findByText(/This score is being recalculated/)).toBeInTheDocument();
  });

  it("offers admins the setup when there is no ICP", async () => {
    server.use(
      handlers.loggedIn(),
      http.get(`*/api/companies/${ID}`, () => HttpResponse.json(company({ id: ID }))),
      http.get("*/api/contacts", () => HttpResponse.json({ items: [], next_cursor: null })),
    );
    renderApp(`/companies/${ID}`);

    const link = await screen.findByRole("link", { name: "Set up ICP scoring" });
    expect(link).toHaveAttribute("href", "/settings#icp");
  });
});

// --- helpers --------------------------------------------------------------------------------

type DraftArg = Parameters<typeof toDefinition>[0];

function draftWith(patch: { [K in keyof DraftArg]?: Partial<DraftArg[K]> }): DraftArg {
  const off = { enabled: false, importance: 3, must_have: false };
  const draft: DraftArg = {
    industry: { ...off, industries: [] },
    size: { ...off, min: "", max: "" },
    country: { ...off, countries: [] },
    business_model: { ...off, models: [] },
    keywords: { ...off, keywords: [] },
    has_contacts: { ...off, min_contacts: "1" },
  };
  for (const [kind, value] of Object.entries(patch)) {
    Object.assign(draft[kind as keyof DraftArg], value);
  }
  return draft;
}
