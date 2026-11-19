"use client";

/**
 * Main navigation of the signed-in shell (task B3).
 *
 * Needed to move between the (still empty) screens. Links are filtered by the user's role for
 * convenience only; hiding a link is not access control, the server enforces access.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useCurrentUser } from "@/lib/auth-context";
import { NAV_ITEMS } from "@/lib/nav-items";

/** Renders the links the current role would normally see and marks the active one. */
export default function NavBar() {
  const { role } = useCurrentUser();
  const pathname = usePathname();

  return (
    <nav className="app-nav" aria-label="Main">
      {NAV_ITEMS.filter((item) => item.roles.includes(role)).map((item) => (
        <Link
          key={item.path}
          href={item.path}
          aria-current={pathname === item.path ? "page" : undefined}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
