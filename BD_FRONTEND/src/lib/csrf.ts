/**
 * CSRF token handling for the browser: the in-memory token and a fetch that sends it (task B12).
 *
 * Needed because the backend (task A8) rejects every state-changing request that lacks the
 * session's `X-CSRF-Token` header. The token lives only in this module's memory (never in
 * `localStorage` or a cookie, which would defeat its purpose); a full page reload loses it and
 * the server layout hands out a fresh one from `/auth/me`. `lib/api-client.ts` installs
 * `createCsrfFetch` on the generated client, so no page or generated code deals with the header.
 * Holds no business rules; the server decides everything.
 */

export const CSRF_HEADER_NAME = "X-CSRF-Token";

/** The exact body the backend sends for any CSRF or Origin failure (same text for every cause). */
export const CSRF_FAILED_DETAIL = "CSRF check failed";

/** Methods that change state and so need the token (GET, HEAD and OPTIONS never do). */
const STATE_CHANGING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** Login is the one state-changing call without a token: nobody is signed in yet. */
const LOGIN_PATH = "/auth/login";

let currentToken: string | null = null;

/** Remembers the CSRF token of the current session (from login or `/auth/me`). */
export function setCsrfToken(token: string): void {
  currentToken = token;
}

/** Returns the remembered CSRF token, or null when none is known (signed out, or not loaded yet). */
export function getCsrfToken(): string | null {
  return currentToken;
}

/** Forgets the token; called on logout because the token dies with the session. */
export function clearCsrfToken(): void {
  currentToken = null;
}

/** True when the request needs the header: it changes state and is not the login call. */
function needsToken(request: Request): boolean {
  if (!STATE_CHANGING_METHODS.has(request.method.toUpperCase())) {
    return false;
  }
  return !new URL(request.url).pathname.endsWith(LOGIN_PATH);
}

/** Returns a copy of the request carrying the token (unchanged headers when there is no token). */
function withToken(request: Request, token: string | null): Request {
  if (!token) {
    return request;
  }
  const headers = new Headers(request.headers);
  headers.set(CSRF_HEADER_NAME, token);
  return new Request(request, { headers });
}

/** True when the response is the backend's CSRF failure (and not the permission 403). */
async function isCsrfFailure(response: Response): Promise<boolean> {
  if (response.status !== 403) {
    return false;
  }
  try {
    // A clone, so the caller can still read the body when this is not a CSRF failure.
    const body: unknown = await response.clone().json();
    return (body as { detail?: unknown } | null)?.detail === CSRF_FAILED_DETAIL;
  } catch {
    return false; // not JSON: certainly not the backend's CSRF body
  }
}

/**
 * Builds the fetch function the API client uses in the browser.
 *
 * State-changing calls (except login) get the `X-CSRF-Token` header. When the backend answers
 * with the CSRF failure, the token is refreshed once through `refreshToken` and the call is
 * repeated once; a second failure is returned as it is, so there is never a retry loop.
 *
 * @param baseFetch the real fetch (or a fake in tests)
 * @param refreshToken asks `/auth/me` for the current token; resolves to null when it cannot
 */
export function createCsrfFetch(
  baseFetch: typeof fetch,
  refreshToken: () => Promise<string | null>,
): typeof fetch {
  return async (input, init) => {
    const request = input instanceof Request && !init ? input : new Request(input, init);
    if (!needsToken(request)) {
      return baseFetch(request);
    }

    // The body can be read only once, so keep an untouched copy for the possible retry.
    const retryCopy = request.clone();
    const response = await baseFetch(withToken(request, getCsrfToken()));
    if (!(await isCsrfFailure(response))) {
      return response;
    }

    const freshToken = await refreshToken();
    if (!freshToken) {
      return response; // the session is gone or the backend is down: report the original failure
    }
    setCsrfToken(freshToken);
    return baseFetch(withToken(retryCopy, freshToken));
  };
}
