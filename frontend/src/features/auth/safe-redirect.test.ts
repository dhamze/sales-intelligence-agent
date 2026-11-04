import { describe, expect, it } from "vitest";

import { safeRedirect } from "./safe-redirect";

describe("safeRedirect", () => {
  it.each(["/companies", "/companies?q=acme&industry=Software", "/contacts/123"])(
    "allows same-site path %s",
    (path) => {
      expect(safeRedirect(path)).toBe(path);
    },
  );

  it.each([
    undefined,
    "",
    "https://evil.example/phish",
    "//evil.example", // protocol-relative: leaves the site
    "/\\evil.example", // some browsers treat backslash like a slash
    "javascript:alert(1)",
    "companies",
  ])("falls back to the app home for unsafe target %s", (target) => {
    expect(safeRedirect(target)).toBe("/companies");
  });
});
