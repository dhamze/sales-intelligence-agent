import type { ErrorEvent } from "@sentry/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/client";

import { filterBreadcrumb, filterEvent } from "./monitoring";

const event = (): ErrorEvent => ({
  type: undefined,
  request: { url: "https://sia.example/companies?q=Initech&industry=Software" },
});

describe("error reporting privacy", () => {
  it("doesn't report expected API errors", () => {
    const notFound = new ApiError(404, { error: { code: "not_found", message: "x" } });
    expect(filterEvent(event(), { originalException: notFound })).toBeNull();
  });

  it("reports server errors and real bugs, without the query string", () => {
    const serverError = new ApiError(500, { error: { code: "internal_error", message: "x" } });
    expect(filterEvent(event(), { originalException: serverError })?.request?.url).toBe(
      "https://sia.example/companies",
    );
    expect(filterEvent(event(), { originalException: new TypeError("boom") })).not.toBeNull();
  });

  it("drops console output and strips query strings from breadcrumbs", () => {
    expect(filterBreadcrumb({ category: "console", message: "secret" })).toBeNull();
    const crumb = filterBreadcrumb({
      category: "navigation",
      data: { from: "/companies?q=acme", to: "/companies/1?tab=x" },
    });
    expect(crumb?.data).toEqual({ from: "/companies", to: "/companies/1" });
    const fetchCrumb = filterBreadcrumb({ category: "fetch", data: { url: "/api/x?q=1" } });
    expect(fetchCrumb?.data?.url).toBe("/api/x");
  });
});
