/**
 * Tests for the role filter of the navigation entries (task B4).
 *
 * Needed so a change to `NAV_ITEMS` that shows the wrong links to a role is caught. The filter
 * is cosmetic only: the server enforces access whatever the menu shows.
 */
import { describe, expect, it } from "vitest";

import type { UserRole } from "@/lib/api-client";
import { NAV_ITEMS } from "@/lib/nav-items";

const COMMON_LABELS = ["Leads", "Campaigns", "Review", "Outbox", "My profile"];
// Menu order matters: Admin and Users sit before "My profile", which is always last.
const ADMIN_LABELS = ["Leads", "Campaigns", "Review", "Outbox", "Admin", "Users", "My profile"];

/** Labels the menu would show for a role, using the same filter as `NavBar`. */
function labelsFor(role: UserRole): string[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role)).map((item) => item.label);
}

describe("NAV_ITEMS", () => {
  it("rep: sees the common links and no Admin or Users link", () => {
    expect(labelsFor("rep")).toEqual(COMMON_LABELS);
  });

  it("manager: sees the common links and no Admin or Users link", () => {
    expect(labelsFor("manager")).toEqual(COMMON_LABELS);
  });

  it("admin: sees the common links plus Admin and Users", () => {
    expect(labelsFor("admin")).toEqual(ADMIN_LABELS);
  });
});
