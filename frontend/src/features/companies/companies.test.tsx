import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { company, handlers, server } from "@/test/server";
import { renderApp } from "@/test/render";

function companiesApi(pages: Record<string, { items: unknown[]; next_cursor: string | null }>) {
  const requests: URL[] = [];
  server.use(
    http.get("*/api/companies", ({ request }) => {
      const url = new URL(request.url);
      requests.push(url);
      return HttpResponse.json(pages[url.searchParams.get("cursor") ?? "first"]);
    }),
  );
  return requests;
}

describe("Companies page", () => {
  it("redirects to login when not authenticated, remembering the page", async () => {
    server.use(handlers.loggedOut());
    const { router } = renderApp("/companies?q=acme");

    await screen.findByRole("heading", { name: "Log in" });
    expect(router.state.location.pathname).toBe("/login");
    expect(router.state.location.search).toEqual({ redirect: "/companies?q=acme" });
  });

  it("lists companies and loads the next page with the cursor", async () => {
    server.use(handlers.loggedIn(), handlers.facets());
    const requests = companiesApi({
      first: { items: [company({ name: "Initech" })], next_cursor: "page-2" },
      "page-2": { items: [company({ name: "Globex", domain: "globex.com" })], next_cursor: null },
    });
    const { user } = renderApp("/companies");

    expect(await screen.findByRole("link", { name: "Initech" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByRole("link", { name: "Globex" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    expect(requests.at(-1)?.searchParams.get("cursor")).toBe("page-2");
  });

  it("puts the search in the URL and sends it to the API (debounced)", async () => {
    server.use(handlers.loggedIn(), handlers.facets());
    const requests = companiesApi({ first: { items: [company()], next_cursor: null } });
    const { user, router } = renderApp("/companies");
    await screen.findByRole("link", { name: "Initech" });

    await user.type(screen.getByLabelText("Search companies"), "init");

    // Wait for the request itself (not just the URL): on slow machines it is sent a moment later.
    await waitFor(() => {
      expect(requests.filter((r) => r.searchParams.get("q") === "init")).toHaveLength(1);
    });
    expect(router.state.location.search).toEqual({ q: "init" });
    // Debounced: the API only ever saw the finished word, never "i", "in" or "ini".
    const searchedTerms = requests.map((r) => r.searchParams.get("q")).filter(Boolean);
    expect(searchedTerms).toEqual(["init"]);
  });

  it("offers to clear filters when nothing matches", async () => {
    server.use(handlers.loggedIn(), handlers.facets());
    companiesApi({ first: { items: [], next_cursor: null } });
    const { user, router } = renderApp("/companies?q=zzz");

    expect(await screen.findByText("No companies match your filters")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));

    await waitFor(() => {
      expect(router.state.location.search).toEqual({});
    });
  });

  it("shows a duplicate-domain error with a link to the existing company", async () => {
    server.use(
      handlers.loggedIn(),
      handlers.facets(),
      http.post("*/api/companies", () =>
        HttpResponse.json(
          {
            error: {
              code: "domain_taken",
              message: "A company with this domain already exists.",
              details: [{ existing_company_id: "11111111-1111-4111-8111-111111111111" }],
            },
          },
          { status: 409 },
        ),
      ),
    );
    companiesApi({ first: { items: [], next_cursor: null } });
    const { user } = renderApp("/companies");

    await user.click(await screen.findByRole("button", { name: "New company" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Name"), "Initech again");
    await user.type(within(dialog).getByLabelText("Website"), "initech.com");
    await user.click(within(dialog).getByRole("button", { name: "Create company" }));

    expect(
      await within(dialog).findByText("A company with this domain already exists."),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Open the existing company" })).toHaveAttribute(
      "href",
      "/companies/11111111-1111-4111-8111-111111111111",
    );
  });

  it("validates required fields before calling the API", async () => {
    server.use(handlers.loggedIn(), handlers.facets());
    companiesApi({ first: { items: [], next_cursor: null } });
    const { user } = renderApp("/companies");

    await user.click(await screen.findByRole("button", { name: "New company" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Employees"), "lots");
    await user.click(within(dialog).getByRole("button", { name: "Create company" }));

    expect(await within(dialog).findByText("Enter the company name.")).toBeInTheDocument();
    expect(within(dialog).getByText("Enter a whole number.")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Name")).toHaveAttribute("aria-invalid", "true");
  });
});

describe("Company page", () => {
  const initech = company({ id: "22222222-2222-4222-8222-222222222222" });

  function companyApi() {
    server.use(
      http.get("*/api/companies/:id", () => HttpResponse.json(initech)),
      http.get("*/api/contacts", () => HttpResponse.json({ items: [], next_cursor: null })),
    );
  }

  it("lets admins delete", async () => {
    server.use(handlers.loggedIn("admin"));
    companyApi();
    renderApp(`/companies/${initech.id}`);

    await screen.findByRole("heading", { name: "Initech" });
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("hides delete from members (the API would refuse anyway)", async () => {
    server.use(handlers.loggedIn("member"));
    companyApi();
    renderApp(`/companies/${initech.id}`);

    await screen.findByRole("heading", { name: "Initech" });
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("lets admins fill an empty workspace with sample data", async () => {
    let loaded = false;
    server.use(
      handlers.loggedIn("owner"),
      handlers.facets(),
      http.get("*/api/companies", () =>
        HttpResponse.json({ items: loaded ? [company()] : [], next_cursor: null }),
      ),
      http.post("*/api/sample-data", () => {
        loaded = true;
        return HttpResponse.json(
          { companies: 12, contacts: 9, ai_profiles: 12, briefs: 12 },
          { status: 201 },
        );
      }),
    );
    const { user } = renderApp("/companies");

    await user.click(await screen.findByRole("button", { name: "Load sample data" }));

    expect(await screen.findByText(/Loaded 12 fictional companies with 12/)).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Initech" })).toBeInTheDocument();
  });

  it("doesn't offer sample data to members", async () => {
    server.use(
      handlers.loggedIn("member"),
      handlers.facets(),
      http.get("*/api/companies", () => HttpResponse.json({ items: [], next_cursor: null })),
    );
    renderApp("/companies");

    expect(await screen.findByText("No companies yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load sample data" })).not.toBeInTheDocument();
  });
});
