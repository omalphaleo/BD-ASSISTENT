/**
 * Frame of every signed-in screen: header, navigation and content area (task B3).
 *
 * Needed so all screens share one look and the user always sees who is signed in and can sign
 * out. It only displays what the server returned from `/auth/me`; it decides no access.
 */
import type { ReactNode } from "react";

import type { UserResponse } from "@/lib/api-client";

import LogoutButton from "./LogoutButton";
import NavBar from "./NavBar";

/** Renders the shell around `children` for the given signed-in user. */
export default function AppShell({
  user,
  children,
}: Readonly<{ user: UserResponse; children: ReactNode }>) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <strong>Alphaleo BD</strong>
        <NavBar />
        <div className="app-user">
          <span>
            {user.email} ({user.role})
          </span>
          <LogoutButton />
        </div>
      </header>
      <main className="app-main">{children}</main>
    </div>
  );
}
