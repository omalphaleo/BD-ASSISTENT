"use client";

/**
 * Email and password login form (task B3).
 *
 * Needed as the entry to the app: it calls the generated `loginAuthLoginPost`, which sets the
 * session cookie. The form decides nothing; it shows the server's answer. Any 401 gets one
 * fixed message, so the screen never reveals whether the email or the password was wrong.
 */
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { loginAuthLoginPost } from "@/lib/api-client";

const AFTER_LOGIN_PATH = "/leads";
const MESSAGE_BAD_CREDENTIALS = "Incorrect email or password.";
const MESSAGE_UNREACHABLE = "Cannot reach the server. Please try again later.";

/** Renders the login form and moves to the app shell after a successful login. */
export default function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    const result = await loginAuthLoginPost({ body: { email, password } });
    setSubmitting(false);

    if (result.data) {
      // replace: Back must not return to the login form. refresh: re-run the server layout
      // so it sees the new session cookie.
      router.replace(AFTER_LOGIN_PATH);
      router.refresh();
      return;
    }

    const status = result.response?.status;
    if (status === 401) {
      setError(MESSAGE_BAD_CREDENTIALS);
    } else if (status === 422) {
      // The backend's 422 body carries only type, loc and msg (never the submitted values).
      const details = result.error?.detail ?? [];
      setError(details.map((item) => item.msg).join(" ") || MESSAGE_BAD_CREDENTIALS);
    } else {
      setError(MESSAGE_UNREACHABLE); // no response: network or CORS failure, or a 5xx
    }
  }

  return (
    <form className="auth-card" onSubmit={handleSubmit}>
      <h1>Alphaleo BD</h1>
      <label className="field">
        <span>Email</span>
        <input
          type="email"
          name="email"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </label>
      <label className="field">
        <span>Password</span>
        <input
          type="password"
          name="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </label>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <button className="button" type="submit" disabled={submitting}>
        {submitting ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
