/**
 * Tests for how the CSRF token follows the session in the browser (task B12).
 *
 * Needed so the token is remembered when the signed-in shell renders (without ever reaching
 * the user context that components can read) and forgotten when the user signs out. The router
 * and the generated logout call are faked; all values are synthetic.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LogoutButton from "@/components/LogoutButton";
import { AuthProvider, useCurrentUser } from "@/lib/auth-context";
import { clearCsrfToken, getCsrfToken, setCsrfToken } from "@/lib/csrf";

// Stand-ins, created with vi.hoisted so the vi.mock factories below can use them.
const { logoutMock, replaceMock, refreshMock } = vi.hoisted(() => ({
  logoutMock: vi.fn(),
  replaceMock: vi.fn(),
  refreshMock: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({ logoutAuthLogoutPost: logoutMock }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, refresh: refreshMock }),
}));

const USER = { id: "1", email: "rep@example.test", role: "rep" } as const;

/** Shows the context user as JSON, so a test can check what components are able to read. */
function ShowUser() {
  return <pre data-testid="user">{JSON.stringify(useCurrentUser())}</pre>;
}

beforeEach(() => {
  vi.resetAllMocks();
  clearCsrfToken();
});

describe("AuthProvider", () => {
  it("remembers the CSRF token it was given", async () => {
    render(
      <AuthProvider user={USER} csrfToken="token-from-me">
        <p>child</p>
      </AuthProvider>,
    );

    await waitFor(() => expect(getCsrfToken()).toBe("token-from-me"));
  });

  it("renews the token when the layout re-renders with a new one (refresh after login)", async () => {
    const { rerender } = render(
      <AuthProvider user={USER} csrfToken="first">
        <p>child</p>
      </AuthProvider>,
    );
    await waitFor(() => expect(getCsrfToken()).toBe("first"));

    rerender(
      <AuthProvider user={USER} csrfToken="second">
        <p>child</p>
      </AuthProvider>,
    );

    await waitFor(() => expect(getCsrfToken()).toBe("second"));
  });

  it("does not put the token into the user that components can read", () => {
    render(
      <AuthProvider user={USER} csrfToken="never-in-context">
        <ShowUser />
      </AuthProvider>,
    );

    expect(screen.getByTestId("user").textContent).toBe(JSON.stringify(USER));
    expect(screen.getByTestId("user").textContent).not.toContain("never-in-context");
  });
});

describe("LogoutButton", () => {
  it("successful sign-out: forgets the token and goes to /login", async () => {
    setCsrfToken("session-token");
    logoutMock.mockResolvedValue({ response: { ok: true } });
    render(<LogoutButton />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/login"));
    expect(getCsrfToken()).toBeNull();
  });

  it("failed sign-out (for example a CSRF rejection): keeps the token and shows the error", async () => {
    setCsrfToken("session-token");
    logoutMock.mockResolvedValue({ error: {}, response: { ok: false, status: 403 } });
    render(<LogoutButton />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not sign out");
    expect(getCsrfToken()).toBe("session-token");
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
