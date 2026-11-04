import { expect, test } from "@playwright/test";

import { signUp } from "./helpers";

test("a seller gets a cited account brief with an outreach angle", async ({ page }) => {
  await signUp(page, "Bea Briefer", "Brief Co");

  await page.getByRole("button", { name: "New company" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill("Initech");
  await dialog.getByLabel("Website").fill("initech.com");
  await dialog.getByRole("button", { name: "Create company" }).click();
  await expect(page.getByRole("heading", { name: "Initech" })).toBeVisible();

  // Enrich first, so the brief can cite the website (worker + fake website + fake AI).
  const profile = page.locator("div.rounded-xl", { hasText: "AI profile" });
  await profile.getByRole("button", { name: "Enrich", exact: true }).click();
  await expect(profile.getByText("Quotes verified against the website")).toBeVisible({
    timeout: 30_000,
  });

  const brief = page.locator("div.rounded-xl", { hasText: "Account brief" });
  await brief.getByRole("button", { name: "Generate brief" }).click();
  await expect(brief.getByText("Citations verified")).toBeVisible({ timeout: 30_000 });

  // Every claim links to its quote; website sources link to the page.
  await brief.getByRole("button", { name: "Source W1: show quote" }).first().click();
  const quote = page.getByRole("dialog");
  await expect(quote.getByText(/builds workflow automation software/)).toBeVisible();
  await expect(quote.getByRole("link", { name: /Open page/ })).toHaveAttribute(
    "href",
    "https://initech.com/",
  );
  await page.keyboard.press("Escape");

  const outreach = page.getByRole("region", { name: "Outreach angle" });
  await expect(outreach.getByText(/never sent automatically/)).toBeVisible();

  // Changing the company makes the brief out of date.
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByRole("dialog").getByLabel("Employees").fill("250");
  await page.getByRole("dialog").getByRole("button", { name: /Save/ }).click();
  await expect(brief.getByText(/changed after the brief was written/)).toBeVisible();

  // The spend shows up in Settings.
  await page.goto("/settings");
  const usage = page.locator("div.rounded-xl", { hasText: "AI usage" });
  await expect(usage.getByRole("cell", { name: "Account briefs" })).toBeVisible();
});
