/**
 * The login journey in a real browser (task B4).
 *
 * Needed as the one end-to-end check that login, the role-dependent menu and logout work
 * together against the running backend. It needs the API, the database and two existing test
 * accounts (E2E_REP_*, E2E_ADMIN_*), and the backend must allow the frontend origin (task A8).
 * Since task B12 it also proves the two sides agree on CSRF: the UI's logout works only because
 * the API client sends `X-CSRF-Token`, and a raw call without it is refused.
 */
import { expect, test } from "@playwright/test";

import { readCredentials, submitLoginForm } from "./helpers";

const WRONG_PASSWORD = "definitely-not-the-password";

test.describe("login journey", () => {
  test("wrong password: shows the error and stays on /login", async ({ page }) => {
    const rep = readCredentials("rep");

    await submitLoginForm(page, { email: rep.email, password: WRONG_PASSWORD });

    // p[role="alert"]: Next.js adds its own <div role="alert"> route announcer to every page, so
    // an unscoped getByRole("alert") matches two elements and fails Playwright's strict mode.
    await expect(page.locator('p[role="alert"]')).toHaveText("Incorrect email or password.");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("rep: lands on /leads and sees no Admin or Users link", async ({ page }) => {
    await submitLoginForm(page, readCredentials("rep"));

    await expect(page).toHaveURL(/\/leads$/);
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Leads" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Admin" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Users" })).toHaveCount(0);
  });

  test("admin: sees the Admin and Users links", async ({ page }) => {
    await submitLoginForm(page, readCredentials("admin"));

    await expect(page).toHaveURL(/\/leads$/);
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Admin" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Users" })).toBeVisible();
  });

  test("logout: returns to /login and /leads then redirects back to /login", async ({ page }) => {
    await submitLoginForm(page, readCredentials("rep"));
    await expect(page).toHaveURL(/\/leads$/);

    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);

    await page.goto("/leads");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("CSRF: a state-changing call without the token is refused and the session survives", async ({
    page,
  }) => {
    await submitLoginForm(page, readCredentials("rep"));
    await expect(page).toHaveURL(/\/leads$/);

    // A raw browser call: the right origin and the session cookie, but no X-CSRF-Token header,
    // which is what a forged cross-site request would look like.
    const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
    const outcome = await page.evaluate(async (url) => {
      const response = await fetch(`${url}/auth/logout`, { method: "POST", credentials: "include" });
      return { status: response.status, body: await response.json() };
    }, apiBaseUrl);

    expect(outcome.status).toBe(403);
    expect(outcome.body).toEqual({ detail: "CSRF check failed" });

    // Refused means not executed: the user is still signed in.
    await page.goto("/leads");
    await expect(page).toHaveURL(/\/leads$/);
  });
});
