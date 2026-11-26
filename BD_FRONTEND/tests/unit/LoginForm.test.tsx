/**
 * Component tests for the login form (task B4).
 *
 * Needed so the login screen's behaviour (fixed error messages, redirect after success, busy
 * state) cannot regress unnoticed. The generated API client and the Next.js router are faked,
 * so no request is ever sent, and every email and password below is a synthetic value.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LoginForm from "@/components/LoginForm";
import { clearCsrfToken, getCsrfToken } from "@/lib/csrf";

// Stand-ins, created with vi.hoisted so the vi.mock factories below can use them:
// loginMock replaces the generated login call, replaceMock/refreshMock replace the router.
const { loginMock, replaceMock, refreshMock } = vi.hoisted(() => ({
  loginMock: vi.fn(),
  replaceMock: vi.fn(),
  refreshMock: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({ loginAuthLoginPost: loginMock }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, refresh: refreshMock }),
}));

const FAKE_EMAIL = "someone@example.test";
const FAKE_PASSWORD = "fake-password-for-tests";

/** Renders the form, types the fake credentials and presses "Sign in". */
async function submitFakeCredentials() {
  const user = userEvent.setup();
  render(<LoginForm />);
  await user.type(screen.getByLabelText("Email"), FAKE_EMAIL);
  await user.type(screen.getByLabelText("Password"), FAKE_PASSWORD);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

beforeEach(() => {
  vi.resetAllMocks();
  clearCsrfToken(); // the token store is module state, so reset it between tests
});

describe("LoginForm", () => {
  it("initial render: both fields are required and the Sign in button is enabled", () => {
    render(<LoginForm />);

    expect(screen.getByLabelText("Email")).toBeRequired();
    expect(screen.getByLabelText("Password")).toBeRequired();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("successful login: sends the credentials, then replace('/leads') before refresh()", async () => {
    loginMock.mockResolvedValue({
      data: { id: "1", email: FAKE_EMAIL, role: "rep", csrf_token: "token-from-login" },
      response: { status: 200 },
    });

    await submitFakeCredentials();

    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/leads"));
    expect(loginMock).toHaveBeenCalledWith({
      body: { email: FAKE_EMAIL, password: FAKE_PASSWORD },
    });
    expect(refreshMock).toHaveBeenCalledTimes(1);
    // replace first, so Back cannot return to the login form; then refresh the server layout.
    expect(replaceMock.mock.invocationCallOrder[0]).toBeLessThan(
      refreshMock.mock.invocationCallOrder[0],
    );
  });

  it("successful login: remembers the CSRF token from the answer (in memory only)", async () => {
    loginMock.mockResolvedValue({
      data: { id: "1", email: FAKE_EMAIL, role: "rep", csrf_token: "token-from-login" },
      response: { status: 200 },
    });

    await submitFakeCredentials();

    await waitFor(() => expect(getCsrfToken()).toBe("token-from-login"));
    expect(window.localStorage.getItem("token-from-login")).toBeNull();
    expect(document.cookie).not.toContain("token-from-login");
  });

  it("failed login: keeps no CSRF token", async () => {
    loginMock.mockResolvedValue({ error: {}, response: { status: 401 } });

    await submitFakeCredentials();

    await screen.findByRole("alert");
    expect(getCsrfToken()).toBeNull();
  });

  it("403 (origin or CSRF rejection): shows the general 'request was rejected' message", async () => {
    loginMock.mockResolvedValue({ error: { detail: "CSRF check failed" }, response: { status: 403 } });

    await submitFakeCredentials();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(
      "The request was rejected. Open the app at its configured address and try again.",
    );
  });

  it("401: shows one fixed message that does not say which field was wrong", async () => {
    loginMock.mockResolvedValue({ error: {}, response: { status: 401 } });

    await submitFakeCredentials();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Incorrect email or password.");
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("422: shows only the server's msg texts and none of the submitted values", async () => {
    loginMock.mockResolvedValue({
      error: { detail: [{ msg: "Field required." }, { msg: "Invalid email." }] },
      response: { status: 422 },
    });

    await submitFakeCredentials();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Field required. Invalid email.");
    expect(alert.textContent).not.toContain(FAKE_EMAIL);
    expect(alert.textContent).not.toContain(FAKE_PASSWORD);
  });

  it("no response (network or CORS failure): shows the 'cannot reach the server' message", async () => {
    loginMock.mockResolvedValue({ error: new Error("network"), response: undefined });

    await submitFakeCredentials();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Cannot reach the server. Please try again later.");
  });

  it("while submitting: the button is disabled and reads 'Signing in…', then recovers", async () => {
    // A promise the test resolves by hand, so the busy state can be observed mid-request.
    let finishLogin: (result: unknown) => void = () => {};
    loginMock.mockReturnValue(
      new Promise((resolve) => {
        finishLogin = resolve;
      }),
    );

    await submitFakeCredentials();

    expect(await screen.findByRole("button", { name: "Signing in…" })).toBeDisabled();

    finishLogin({ error: {}, response: { status: 401 } });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });
});
