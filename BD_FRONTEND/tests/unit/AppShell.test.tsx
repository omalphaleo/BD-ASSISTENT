/**
 * Component tests for the signed-in shell (task B4).
 *
 * Needed so the frame every signed-in screen shares (title, user, navigation, sign-out) keeps
 * working, and so admin-only links stay hidden from other roles. Hiding links is cosmetic; the
 * server enforces access. The router and API client are faked, and the users are synthetic.
 */
import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import AppShell from "@/components/AppShell";
import type { UserResponse } from "@/lib/api-client";
import { AuthProvider } from "@/lib/auth-context";

// Stand-in for the Next.js router hooks used by NavBar and LogoutButton (no router in jsdom).
vi.mock("next/navigation", () => ({
  usePathname: () => "/leads",
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
}));

// Stand-in for the generated logout call, so importing LogoutButton never touches the network.
vi.mock("@/lib/api-client", () => ({ logoutAuthLogoutPost: vi.fn() }));

// Stand-in for next/link, which needs the Next.js router at runtime; a plain anchor is enough
// to check which links are shown.
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

/** Renders the shell for a user, wrapped in the provider the real (app) layout supplies. */
function renderShell(user: UserResponse) {
  return render(
    <AuthProvider user={user} csrfToken="test-csrf-token">
      <AppShell user={user}>
        <p>Page body</p>
      </AppShell>
    </AuthProvider>,
  );
}

const REP: UserResponse = { id: "1", email: "rep@example.test", role: "rep" };
const ADMIN: UserResponse = { id: "2", email: "admin@example.test", role: "admin" };

describe("AppShell", () => {
  it("rep: shows the title, email and role, the page body and a Sign out button", () => {
    renderShell(REP);

    expect(screen.getByText("Alphaleo BD")).toBeInTheDocument();
    expect(screen.getByText("rep@example.test (rep)")).toBeInTheDocument();
    expect(screen.getByText("Page body")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("rep: the main navigation has no Admin or Users link", () => {
    renderShell(REP);

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Leads" })).toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  });

  it("admin: the main navigation shows the Admin and Users links", () => {
    renderShell(ADMIN);

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Admin" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Users" })).toBeInTheDocument();
  });
});
