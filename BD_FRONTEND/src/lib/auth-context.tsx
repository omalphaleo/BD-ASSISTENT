"use client";

/**
 * React context that hands the signed-in user to client components (task B3).
 *
 * Needed so the navigation can show the user's email and role without each component calling
 * the API. The server layout loads the user once per page load and seeds this provider; it
 * makes no request of its own and holds no access rules (the server enforces access).
 */
import { createContext, useContext, type ReactNode } from "react";

import type { UserResponse } from "./api-client";

const AuthContext = createContext<UserResponse | null>(null);

/** Provides the already-loaded signed-in user to everything below it. */
export function AuthProvider({ user, children }: Readonly<{ user: UserResponse; children: ReactNode }>) {
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
