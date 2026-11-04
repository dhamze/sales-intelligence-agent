import { screen, waitFor } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { Schemas } from "@/lib/api/client";
import { handlers, server } from "@/test/server";
import { renderApp } from "@/test/render";

const ID = "33333333-3333-4333-8333-333333333333";
const HEADERS = ["Firmenname", "Website", "Branche", "Mitarbeiter"];

function preview(mapping: Record<string, string | null>): Schemas["ImportPreview"] {
  return {
    id: ID,
    entity_type: "companies",
    status: "preview",
    filename: "export.csv",
    row_count: 2,
    headers: HEADERS,
    mapping,
    created_count: 0,
    updated_count: 0,
    unchanged_count: 0,
    invalid_count: 0,
    duplicate_count: 0,
    errors: [],
    created_at: "2026-11-04T10:00:00Z",
    completed_at: null,
    available_fields: ["name", "domain", "website", "industry", "employee_count", "attributes"],
    sample_rows: [{ Firmenname: "SAP", Website: "sap.com", Branche: "Software", Mitarbeiter: "1" }],
    valid_count: 2,
    existing_matches: 0,
    encoding: "utf-8",
    delimiter: ";",
  };
}

const DETECTED = {
  Firmenname: "attributes",
  Website: "website",
  Branche: "attributes",
  Mitarbeiter: "attributes",
};

describe("Import review", () => {
  it("keeps every mapping change even while the preview is still recalculating", async () => {
    let committed: unknown;
    server.use(
      handlers.loggedIn(),
      http.get("*/api/imports/:id", () => HttpResponse.json(preview(DETECTED))),
      http.post("*/api/imports/:id/preview", async ({ request }) => {
        const body = (await request.json()) as { mapping: Record<string, string | null> | null };
        await delay(150); // slow server: the UI shows stale preview data meanwhile
        return HttpResponse.json(preview(body.mapping ?? DETECTED));
      }),
      http.post("*/api/imports/:id/commit", async ({ request }) => {
        committed = await request.json();
        return HttpResponse.json({ ...preview(DETECTED), status: "completed", created_count: 2 });
      }),
      http.get("*/api/imports", () => HttpResponse.json({ items: [], next_cursor: null })),
    );
    const { user } = renderApp(`/imports/${ID}`);
    await screen.findByText("Ready to import");

    // Three changes in quick succession, faster than the preview round-trip.
    await user.selectOptions(screen.getByLabelText("Import column Firmenname as"), "name");
    await user.selectOptions(screen.getByLabelText("Import column Branche as"), "industry");
    await user.selectOptions(
      screen.getByLabelText("Import column Mitarbeiter as"),
      "employee_count",
    );

    expect(screen.getByLabelText("Import column Firmenname as")).toHaveValue("name");
    expect(screen.getByLabelText("Import column Branche as")).toHaveValue("industry");

    const importButton = screen.getByRole("button", { name: /^Import 2 companies$/ });
    await waitFor(() => {
      expect(importButton).toBeEnabled();
    });
    await user.click(importButton);

    await waitFor(() => {
      expect(committed).toEqual({
        mapping: {
          Firmenname: "name",
          Website: "website",
          Branche: "industry",
          Mitarbeiter: "employee_count",
        },
      });
    });
  });

  it("does not offer a field that another column already uses", async () => {
    server.use(
      handlers.loggedIn(),
      http.get("*/api/imports/:id", () => HttpResponse.json(preview(DETECTED))),
      http.post("*/api/imports/:id/preview", () => HttpResponse.json(preview(DETECTED))),
    );
    renderApp(`/imports/${ID}`);
    await screen.findByText("Ready to import");

    const firmenname = screen.getByLabelText("Import column Firmenname as");
    const websiteOption = Array.from(firmenname.querySelectorAll("option")).find(
      (o) => o.value === "website",
    );

    expect(websiteOption).toBeDisabled(); // "Website" column already maps to website
  });
});
