"use client";

/**
 * Logout button in the shell header (task B3).
 *
 * Needed so a user can end the session: it calls the generated `logoutAuthLogoutPost`, which
 * clears the session cookie, then returns to the login page. Holds no rules of its own.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { logoutAuthLogoutPost } from "@/lib/api-client";

const LOGIN_PATH = "/login";

/** Signs the user out and navigates to the login page. */
export default function LogoutButton() {
  const router = useRouter();
  const [failed, setFailed] = useState(false);

  async function handleLogout() {
    setFailed(false);
    const result = await logoutAuthLogoutPost();

    if (result.response?.ok) {
      // refresh drops cached signed-in data so nothing stale stays on screen.
      router.replace(LOGIN_PATH);
      router.refresh();
    } else {
      // Not signed out (network problem): stay put, because /login would bounce a still-valid
      // session straight back into the app.
      setFailed(true);
    }
  }

  return (
    <>
      <button className="button button-secondary" type="button" onClick={handleLogout}>
        Sign out
      </button>
      {failed && (
        <span className="form-error" role="alert">
          Could not sign out. Please try again.
        </span>
      )}
    </>
  );
}
