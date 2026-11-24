/**
 * Layout of every signed-in screen: session check plus the app shell (task B3).
 *
 * Needed so no signed-in screen renders for a signed-out visitor. It asks the backend
 * (`/auth/me`, server-side, with the visitor's own cookie) who is signed in: a 401 redirects to
 * /login before anything renders. A layout does not re-run on client-side navigation, so the
 * check runs on a full page load and on `router.refresh()`; a session that expires in between is
 * caught by the 401 handling in `lib/api-client.ts`. The server still enforces access on every API call.
 */
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import AppShell from "@/components/AppShell";
import { AuthProvider } from "@/lib/auth-context";
import { getSessionState } from "@/lib/auth-server";

/** Wraps the signed-in routes; redirects to /login when nobody is signed in. */
export default async function AppLayout({ children }: Readonly<{ children: ReactNode }>) {
  const session = await getSessionState();

  if (session.status === "signed-out") {
    redirect("/login");
  }
  if (session.status === "unavailable") {
    // Not a redirect: sending the user to /login while the backend is down could loop.
    return (
      <main className="app-main">
        <h1>Backend unavailable</h1>
        <p>The server did not answer. Please try again in a moment.</p>
      </main>
    );
  }

  return (
    <AuthProvider user={session.user}>
      <AppShell user={session.user}>{children}</AppShell>
    </AuthProvider>
  );
}
