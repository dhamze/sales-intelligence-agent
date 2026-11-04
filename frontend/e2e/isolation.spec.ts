import { expect, test } from "@playwright/test";

import { importCsv, signUp } from "./helpers";

test("one organization never sees another organization's data", async ({ browser }) => {
  // Two separate browsers = two separate sessions.
  const acme = await (await browser.newContext()).newPage();
  const globex = await (await browser.newContext()).newPage();

  await signUp(acme, "Alice Owner", "Acme");
  await importCsv(acme, "companies.csv", "Companies");
  await acme.goto("/companies");
  await acme.getByRole("link", { name: "Initech" }).click();
  await expect(acme.getByRole("heading", { name: "Initech" })).toBeVisible();
  const acmeCompanyUrl = acme.url();

  await signUp(globex, "Bob Owner", "Globex");
  await expect(globex.getByText("No companies yet")).toBeVisible();

  // Searching doesn't find Acme's companies...
  await globex.getByLabel("Search companies").fill("initech");
  await expect(globex.getByText("No companies match your filters")).toBeVisible();

  // ...and opening one by its URL doesn't reveal it.
  await globex.goto(acmeCompanyUrl);
  await expect(globex.getByText("This company doesn't exist or was deleted.")).toBeVisible();
  await expect(globex.getByRole("heading", { name: "Initech" })).toHaveCount(0);
});

test("protected pages require login", async ({ page }) => {
  await page.goto("/settings");

  await expect(page).toHaveURL(/\/login\?redirect=%2Fsettings/);
  await expect(page.getByRole("heading", { name: "Log in" })).toBeVisible();
});
