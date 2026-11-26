/**
 * Tests for the role filter of the navigation entries (task B4).
 *
 * Needed so a change to `NAV_ITEMS` that shows the wrong links to a role is caught. The filter
 * is cosmetic only: the server enforces access whatever the menu shows.
 */
import { describe, expect, it } from "vitest";

import type { UserRole } from "@/lib/api-client";
import { NAV_ITEMS } from "@/lib/nav-items";

const COMMON_LABELS = [
  "Leads",
  "Import",
  "Quarantine",
  "Campaigns",
  "Review",
  "Outbox",
  "My profile",
];
// Managers also review duplicates (REVIEW_DUPLICATES: manager and admin).
const MANAGER_LABELS = [
  "Leads",
  "Import",
  "Quarantine",
  "Duplicates",
  "Campaigns",
  "Review",
  "Outbox",
  "My profile",
];
// Menu order matters: Admin screens and Users sit before "My profile", which is always last.
const ADMIN_LABELS = [
  "Leads",
  "Import",
  "Quarantine",
  "Duplicates",
  "Campaigns",
  "Review",
  "Outbox",
  "Admin",
  "Source profiles",
  "Mappings",
  "Users",
  "My profile",
];

/** Labels the menu would show for a role, using the same filter as `NavBar`. */
function labelsFor(role: UserRole): string[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role)).map((item) => item.label);
}

describe("NAV_ITEMS", () => {
  it("rep: sees the common links and no Admin or Users link", () => {
    expect(labelsFor("rep")).toEqual(COMMON_LABELS);
  });

  it("manager: sees the common links plus Duplicates, and no Admin or Users link", () => {
    expect(labelsFor("manager")).toEqual(MANAGER_LABELS);
  });

  it("admin: sees every link, including the Admin screens and Users", () => {
    expect(labelsFor("admin")).toEqual(ADMIN_LABELS);
  });
});
