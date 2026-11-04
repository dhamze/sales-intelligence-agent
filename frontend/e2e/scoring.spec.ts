import { expect, test } from "@playwright/test";

import { importCsv, signUp } from "./helpers";

test("an admin defines the ICP and the team works the best-fitting companies first", async ({
  page,
}) => {
  await signUp(page, "Sam Scorer", "Score Co");
  await importCsv(page, "scoring-companies.csv", "Companies");

  // Before an ICP exists, the list invites the team to set one up.
  await page.goto("/companies");
  await page.getByRole("link", { name: "Set up ICP scoring" }).click();

  const icp = page.locator("#icp");
  await icp.getByRole("checkbox", { name: /^Industry/ }).check();
  await icp.getByLabel("Add industries").fill("Software");
  await icp.getByLabel("Add industries").press("Enter");
  await icp.getByRole("checkbox", { name: /^Company size/ }).check();
  await icp.getByLabel("Minimum employees").fill("50");
  await icp.getByLabel("Maximum employees").fill("500");

  // The live preview scores the imported companies without saving anything.
  const best = icp.getByRole("list", { name: "Best fits" });
  await expect(best.getByRole("listitem").first()).toContainText("Initech");

  await icp.getByRole("button", { name: "Save ICP" }).click();
  // The worker rescores every company in the background.
  await expect(icp.getByText(/All 3 companies are scored/)).toBeVisible({ timeout: 30_000 });

  await page.goto("/companies");
  await page.getByRole("button", { name: "ICP fit" }).click();
  const firstRow = page.getByRole("row").nth(1);
  await expect(firstRow).toContainText("Initech");
  await expect(firstRow.getByLabel("Tier A")).toBeVisible();

  await page.getByRole("button", { name: /ICP tier/ }).click();
  await page.getByRole("menuitemcheckbox", { name: /Poor fit/ }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("link", { name: "Globex" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Initech" })).toHaveCount(0);

  // The company page explains the score criterion by criterion.
  await page.getByRole("link", { name: "Globex" }).click();
  const breakdown = page.getByRole("list", { name: "Score breakdown" });
  await expect(breakdown.getByText("Retail is not in your ICP (Software)")).toBeVisible();
  await expect(breakdown.getByText(/5,000 employees is outside your ICP/)).toBeVisible();
});
