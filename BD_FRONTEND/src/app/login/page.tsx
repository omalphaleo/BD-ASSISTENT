/**
 * Login page (task B3).
 *
 * Needed as the public entry to the app. A visitor who is already signed in is sent straight to
 * the app, so the form is only shown to signed-out visitors. The form itself is a client component.
 */
import { redirect } from "next/navigation";

import LoginForm from "@/components/LoginForm";
import { getSessionState } from "@/lib/auth-server";

/** Redirects signed-in visitors to /leads; otherwise renders the login form. */
export default async function LoginPage() {
  const session = await getSessionState();
  if (session.status === "signed-in") {
    redirect("/leads");
  }

  return (
    <main className="auth-page">
      <LoginForm />
    </main>
  );
}
