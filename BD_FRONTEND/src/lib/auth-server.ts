/**
 * Server-side session lookup: asks the backend who is signed in (task B3).
 *
 * Needed because layouts and pages decide what to render (shell, redirect to /login) before
 * the browser gets anything. The browser's cookie is forwarded on this one request only, in the
 * call's own headers; it is never set on the shared API client, which would leak one user's
 * session into another request. The server only reports what `/auth/me` says; it decides nothing.
 */
import "server-only";

import { cookies } from "next/headers";

import { meAuthMeGet, type UserResponse } from "./api-client";

/** Outcome of the session check; "unavailable" means the backend could not answer. */
export type SessionState =
  | { status: "signed-in"; user: UserResponse }
  | { status: "signed-out" }
  | { status: "unavailable" };

/**
 * Returns the backend address for server-to-server calls.
 *
 * Inside Docker the browser-facing `localhost:8000` is not the API, so `API_INTERNAL_URL`
 * can point at the compose service. When it is unset or empty we fall back to the public URL.
 *
 * Raises:
 *   Error: when neither variable is set.
 */
function readServerApiBaseUrl(): string {
  const baseUrl = process.env.API_INTERNAL_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl) {
    throw new Error(
      "Set API_INTERNAL_URL or NEXT_PUBLIC_API_BASE_URL (see BD_FRONTEND/.env.local.example).",
    );
  }
  return baseUrl;
}

/**
 * Looks up the current user with the request's session cookie.
 *
 * Returns "signed-out" on a 401 or when there is no cookie at all, and "unavailable" for any
 * other failure (backend down, 5xx), so callers can show an error instead of redirecting in a loop.
 */
export async function getSessionState(): Promise<SessionState> {
  const cookieHeader = (await cookies()).toString();
  if (!cookieHeader) {
    return { status: "signed-out" }; // no cookie, so the backend would answer 401 anyway
  }

  const result = await meAuthMeGet({
    baseUrl: readServerApiBaseUrl(),
    headers: { cookie: cookieHeader },
    cache: "no-store", // the answer depends on the caller's cookie; never reuse it
  });

  if (result.data) {
    return { status: "signed-in", user: result.data };
  }
  if (result.response?.status === 401) {
    return { status: "signed-out" };
  }
  return { status: "unavailable" };
}
