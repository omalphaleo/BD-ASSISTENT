/**
 * Home route "/" (task B3): only decides where to send the visitor.
 *
 * Replaces the B1 placeholder. Signed-in visitors go to the app (/leads), everyone else to /login.
 * It renders nothing itself and holds no business rules.
 */
import { redirect } from "next/navigation";

import { getSessionState } from "@/lib/auth-server";

/** Redirects by session state; never renders content. */
export default async function HomePage() {
  const session = await getSessionState();
  redirect(session.status === "signed-in" ? "/leads" : "/login");
}
