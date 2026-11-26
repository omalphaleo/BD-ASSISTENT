/**
 * Runtime setup and public entry point for the generated API client (tasks B2, B3, B12).
 *
 * Needed because the generated code in `src/lib/api/` must never be hand-edited, yet every call
 * needs the backend base URL, the session cookie and (B12) the CSRF token. Pages import the API
 * functions and types from here, so this is the single place where the CSRF header is added; the
 * logic itself lives in `lib/csrf.ts`.
 * Also redirects the browser to /login when a call (other than login itself) returns 401 (B3).
 * Holds no business rules; the server decides everything.
 */
import { client } from "./api/client.gen";
import { meAuthMeGet } from "./api/sdk.gen";
import type { SessionUserResponse } from "./api/types.gen";
import { createCsrfFetch } from "./csrf";

/**
 * Reads the backend base URL from the public environment.
 *
 * Raises:
 *   Error: when `NEXT_PUBLIC_API_BASE_URL` is missing, so a misconfigured build fails loudly
 *   instead of sending requests to the wrong host.
 */
function readApiBaseUrl(): string {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL is not set (see BD_FRONTEND/.env.local.example).");
  }
  return baseUrl;
}

client.setConfig({
  baseUrl: readApiBaseUrl(),
  // The session is an HttpOnly cookie; the browser only sends it cross-origin with "include".
  credentials: "include",
});

const LOGIN_PATH = "/auth/login";
const LOGIN_PAGE = "/login";

// Browser only: the server-side session check (auth-server.ts) handles its own 401 and only
// reads (GET /auth/me), so the shared server client must carry no browser behaviour.
if (typeof window !== "undefined") {
  // Adds `X-CSRF-Token` to every POST, PUT, PATCH and DELETE except login, and on a CSRF failure
  // refreshes the token from GET /auth/me and retries once (contract: milestone/m1.md section 16).
  // Without `.bind`, calling fetch through a variable throws "Illegal invocation" in browsers.
  client.setConfig({
    fetch: createCsrfFetch(window.fetch.bind(window), async () => {
      const result = await meAuthMeGet();
      return result.data?.csrf_token ?? null;
    }),
  });

  // A 401 on any call means the session is gone (for example expired mid-use), so send the user
  // to the login page with a full page load, which also re-runs the server layout. The login call
  // itself is excluded: there a 401 means a wrong password, and the form must show its own
  // message instead of reloading.
  client.interceptors.response.use((response, request) => {
    const isLoginCall = new URL(request.url).pathname.endsWith(LOGIN_PATH);
    if (response.status === 401 && !isLoginCall && window.location.pathname !== LOGIN_PAGE) {
      // A full load is intended (the server layout must re-check the session) and this code runs
      // outside React, where useRouter() is not available.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign(LOGIN_PAGE);
    }
    return response;
  });
}

/** The signed-in user as pages see it: the server's answer without the CSRF token. */
export type UserResponse = Omit<SessionUserResponse, "csrf_token">;

// Re-exported so pages depend on this module, and a backend schema change that breaks a
// signature or type fails `npm run typecheck` here first.
export {
  healthHealthGet,
  loginAuthLoginPost,
  logoutAuthLogoutPost,
  meAuthMeGet,
} from "./api/sdk.gen";
export type {
  ErrorResponse,
  LoginRequest,
  SessionUserResponse,
  UserRole,
  ValidationErrorResponse,
} from "./api/types.gen";
export { client as apiClient };
