// Playwright configuration for the browser journeys in tests/e2e (task B4).
// Needed so `npm run test:e2e` drives a real browser against the running app and backend; it is
// not part of `make check` because it needs the database and the API to be started first.
import { existsSync } from "node:fs";

import { defineConfig, devices } from "@playwright/test";

// Load .env.local (git-ignored) so the E2E_* test accounts can live there; Playwright does not
// read it by itself. Variables already set in the shell win over the file.
if (existsSync(".env.local")) {
  process.loadEnvFile(".env.local");
}

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false, // journeys share the same test accounts and database
  reporter: "list",
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      // E2E_BROWSER_CHANNEL (for example "msedge" or "chrome") runs an installed browser, for
      // machines where Playwright's own Chromium download is blocked. Unset: bundled Chromium.
      use: { ...devices["Desktop Chrome"], channel: process.env.E2E_BROWSER_CHANNEL || undefined },
    },
  ],
  // Starts the frontend when it is not running yet; the backend must already be up.
  webServer: {
    command: "npm run dev",
    url: BASE_URL,
    reuseExistingServer: true,
  },
});
