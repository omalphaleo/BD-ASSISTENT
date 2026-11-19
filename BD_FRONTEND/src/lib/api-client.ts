/**
 * Runtime setup and public entry point for the generated API client (task B2).
 *
 * Needed because the generated code in `src/lib/api/` must never be hand-edited, yet every call
 * needs the backend base URL and the session cookie. Pages import the API functions and types
 * from here, so this is also the single place where B12 adds the CSRF header.
 * Also redirects the browser to /login when a call (other than login itself) returns 401 (B3).
 * Holds no business rules; the server decides everything.
 */
import { client } from "./api/client.gen";

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

// Browser only: the server-side session check (auth-server.ts) handles its own 401 and the shared
// server client must not carry browser behaviour. A 401 on any call means the session is gone
// (for example expired mid-use), so send the user to the login page with a full page load, which
// also re-runs the server layout. The login call itself is excluded: there a 401 means a wrong
// password, and the form must show its own message instead of reloading.
if (typeof window !== "undefined") {
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

// Re-exported so pages depend on this module, and a backend schema change that breaks a
// signature or type fails `npm run typecheck` here first.
export {
  healthHealthGet,
  loginAuthLoginPost,
  logoutAuthLogoutPost,
  meAuthMeGet,
} from "./api/sdk.gen";
export type { HttpValidationError, LoginRequest, UserResponse, UserRole } from "./api/types.gen";
export { client as apiClient };
