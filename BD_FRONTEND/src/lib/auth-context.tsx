"use client";

/**
 * React context that hands the signed-in user to client components (tasks B3, B12).
 *
 * Needed so the navigation can show the user's email and role without each component calling
 * the API, and (B12) so the session's CSRF token reaches the browser. The server layout loads
 * the user once per page load and seeds this provider; it makes no request of its own and holds
 * no access rules (the server enforces access). The token goes straight into the in-memory store
 * in `lib/csrf.ts` and is never put in the context, so no component can read or log it.
 */
import { createContext, useContext, useEffect, type ReactNode } from "react";

import type { UserResponse } from "./api-client";
import { setCsrfToken } from "./csrf";

const AuthContext = createContext<UserResponse | null>(null);

/**
 * Provides the already-loaded signed-in user to everything below it and remembers the CSRF
 * token. A full page load or `router.refresh()` re-runs the layout, so the token is renewed
 * whenever the session is re-checked.
 */
export function AuthProvider({
  user,
  csrfToken,
  children,
}: Readonly<{ user: UserResponse; csrfToken: string; children: ReactNode }>) {
  // An effect, not the render body: remembering the token is a side effect outside React.
  useEffect(() => {
    setCsrfToken(csrfToken);
  }, [csrfToken]);

  return <AuthContext.Provider value={user}>{children}</AuthContext.Provider>;
}

/**
 * Returns the signed-in user.
 *
 * Raises:
 *   Error: when used outside `AuthProvider` (only the `(app)` layout provides it).
 */
export function useCurrentUser(): UserResponse {
  const user = useContext(AuthContext);
  if (!user) {
    throw new Error("useCurrentUser must be used inside AuthProvider.");
  }
  return user;
}
