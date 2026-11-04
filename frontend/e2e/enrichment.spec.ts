import { expect, test } from "@playwright/test";

import { signUp } from "./helpers";

test("enriching a company builds a cited profile and fills in empty fields", async ({ page }) => {
  await signUp(page, "Eve Enricher", "Enrich Co");

  await page.getByRole("button", { name: "New company" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill("Initech");
  await dialog.getByLabel("Website").fill("initech.com");
  await dialog.getByRole("button", { name: "Create company" }).click();
  await expect(page.getByRole("heading", { name: "Initech" })).toBeVisible();

  // Enrich: the API queues a job, the worker reads the (fake) website and asks the (fake) AI.
  const profile = page.locator("div.rounded-xl", { hasText: "AI profile" });
  await profile.getByRole("button", { name: "Enrich", exact: true }).click();
  await expect(profile.getByText("Quotes verified against the website")).toBeVisible({
    timeout: 30_000,
  });
  await expect(profile.getByText("Fintech")).toBeVisible();
  await expect(profile.getByText(/headquartered in Berlin, Germany/).first()).toBeVisible();
  await expect(profile.getByRole("link", { name: "initech.com" }).first()).toHaveAttribute(
    "href",
    "https://initech.com/",
  );

  // Empty company fields were filled from verified facts.
  const details = page.locator("div.rounded-xl", { hasText: "Details" }).first();
  await expect(details.getByText("Berlin, Germany")).toBeVisible();
  await expect(details.getByText("Fintech")).toBeVisible();
});
