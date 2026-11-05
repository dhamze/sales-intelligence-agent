import { expect, test } from "@playwright/test";

import { signUp } from "./helpers";

test("a new admin explores the product with fictional sample data", async ({ page }) => {
  await signUp(page, "Sam Sample", "Sample Co");

  await page.getByRole("button", { name: "Load sample data" }).click();
  await expect(page.getByText(/Loaded 12 fictional companies/)).toBeVisible();

  // Scored against the sample ICP straight away: best fits first.
  await page.getByRole("button", { name: "ICP fit" }).click();
  const firstRow = page.getByRole("row").nth(1);
  await expect(firstRow.getByLabel("Tier A")).toBeVisible();

  await firstRow.getByRole("link").first().click();
  await expect(page.getByRole("list", { name: "Score breakdown" })).toBeVisible();
  await expect(page.getByText("Fictional company")).toBeVisible();
});
