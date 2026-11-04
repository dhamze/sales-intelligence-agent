import { expect, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

export const fixture = (name: string): string =>
  fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url));

/** A unique, valid email per test run (tests never depend on each other's data). */
export function uniqueEmail(prefix: string): string {
  return `${prefix}.${Date.now()}.${Math.random().toString(36).slice(2, 8)}@example.com`;
}

export const PASSWORD = "e2e-password-long-enough";

export async function signUp(page: Page, name: string, organization: string): Promise<string> {
  const email = uniqueEmail(name.split(" ")[0]?.toLowerCase() ?? "user");
  await page.goto("/signup");
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel("Company or team").fill(organization);
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page.getByRole("heading", { name: "Companies" })).toBeVisible();
  return email;
}

export async function importCsv(
  page: Page,
  file: string,
  entity: "Companies" | "Contacts",
): Promise<void> {
  await page.goto("/imports/new");
  // Click the card, like a person would (the radio inside it is visually hidden).
  const option = page.getByRole("radio", { name: new RegExp(`^${entity}`) });
  await page.locator("label", { has: option }).click();
  await expect(option).toBeChecked();
  await page.getByLabel("Choose CSV file").setInputFiles(fixture(file));
  await expect(page.getByText("Ready to import")).toBeVisible();
  await page.getByRole("button", { name: /^Import \d/ }).click();
  await expect(page.getByText("Import complete.").first()).toBeVisible();
}
