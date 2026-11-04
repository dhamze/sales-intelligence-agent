import { expect, test } from "@playwright/test";

import { fixture, importCsv, PASSWORD, signUp } from "./helpers";

test("a new team signs up, imports accounts, finds and works an account", async ({ page }) => {
  const email = await signUp(page, "Dana Scully", "Acme Sales");
  await expect(page.getByText("No companies yet")).toBeVisible();

  // Import companies: the review step shows what will happen before anything is saved.
  await page.goto("/imports/new");
  await page.getByLabel("Choose CSV file").setInputFiles(fixture("companies.csv"));
  const stats = page.locator("main [aria-live=polite]");
  await expect(stats).toContainText("Rows in file4");
  await expect(stats).toContainText("Ready to import3");
  await expect(page.getByRole("cell", { name: "Not a public domain name." })).toBeVisible();
  await page.getByRole("button", { name: "Import 3 companies" }).click();
  await expect(page.getByText("Import complete.").first()).toBeVisible();

  // Contacts are linked to the imported companies by email domain.
  await importCsv(page, "contacts.csv", "Contacts");

  // Find a company despite a typo, and open it.
  await page.goto("/companies");
  await page.getByLabel("Search companies").fill("initeck");
  await expect(page).toHaveURL(/q=initeck/);
  await page.getByRole("link", { name: "Initech" }).click();
  await expect(page.getByRole("heading", { name: "Initech" })).toBeVisible();
  await expect(page.getByText("1,200")).toBeVisible(); // "1,200" in the CSV -> 1200 employees
  await expect(page.getByText("Gold")).toBeVisible(); // unknown column kept as an extra field
  await expect(page.getByRole("button", { name: "Peter Gibbons" })).toBeVisible();

  // Add a contact by hand.
  await page.getByRole("button", { name: "Add contact" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("First name").fill("Michael");
  await dialog.getByLabel("Last name").fill("Bolton");
  await dialog.getByRole("button", { name: "Create contact" }).click();
  await expect(page.getByRole("button", { name: "Michael Bolton" })).toBeVisible();

  // Log out, log back in: everything is still there.
  await page.getByRole("button", { name: /Dana Scully/ }).click();
  await page.getByRole("menuitem", { name: "Log out" }).click();
  await expect(page.getByRole("heading", { name: "Log in" })).toBeVisible();
  await page.goto("/contacts");
  await expect(page).toHaveURL(/\/login\?redirect=%2Fcontacts/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/contacts$/); // back where the user wanted to go
  await expect(page.getByRole("button", { name: "Michael Bolton" })).toBeVisible();
  await expect(page.getByRole("row", { name: /Hank Scorpio.*Globex Corporation/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /Bob Slydell/ })).not.toContainText("Initech");
});
