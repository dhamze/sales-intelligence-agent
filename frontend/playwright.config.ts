import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests: the production build of the web app (`vite preview`) against the real API
 * and database. Locally, start PostgreSQL first (`docker compose up -d db`) and build the app
 * (`npm run build`); Playwright starts the API and the preview server, or reuses running ones.
 */
const CI = Boolean(process.env.CI);
const WEB_URL = "http://localhost:4173";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  reporter: CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: WEB_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "uv run uvicorn sia.main:create_app --factory --port 8000",
      cwd: "..",
      url: "http://127.0.0.1:8000/health/ready",
      reuseExistingServer: !CI,
      timeout: 60_000,
    },
    {
      command: "npm run preview",
      url: WEB_URL,
      reuseExistingServer: !CI,
      timeout: 60_000,
    },
  ],
});
