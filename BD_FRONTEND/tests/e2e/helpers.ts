/**
 * Shared helpers for the Playwright journeys (task B4).
 *
 * Needed so the test accounts come from environment variables (never from the repository) and
 * every journey logs in the same way. The accounts must already exist in the test database.
 */
import type { Page } from "@playwright/test";

export type Credentials = { email: string; password: string };

/**
 * Reads the credentials of a test account from the environment.
 *
 * Args:
 *     role: which account to read; maps to E2E_REP_* or E2E_ADMIN_*.
 *
 * Raises:
 *     Error: when a variable is missing, so the journey fails with a clear message instead of
 *     a confusing "Incorrect email or password."
 */
export function readCredentials(role: "rep" | "admin"): Credentials {
  const prefix = `E2E_${role.toUpperCase()}`;
  const email = process.env[`${prefix}_EMAIL`];
  const password = process.env[`${prefix}_PASSWORD`];
  if (!email || !password) {
    throw new Error(
      `Set ${prefix}_EMAIL and ${prefix}_PASSWORD (see BD_FRONTEND/.env.local.example); ` +
        "the account must already exist in the test database.",
    );
  }
  return { email, password };
}

/** Opens /login and submits the credentials through the form, like a user would. */
export async function submitLoginForm(page: Page, credentials: Credentials): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(credentials.email);
  await page.getByLabel("Password").fill(credentials.password);
  await page.getByRole("button", { name: "Sign in" }).click();
}
