/**
 * Navigation entries for the signed-in shell (task B3).
 *
 * Needed so the menu is defined in one place. The `roles` list only decides which links are
 * shown: it is a convenience, not access control. The server rejects forbidden requests
 * regardless of what the menu shows.
 */
import type { UserRole } from "./api-client";

export type NavItem = {
  label: string;
  path: string;
  /** Roles that see this link in the menu (cosmetic only). */
  roles: readonly UserRole[];
};

const ALL_ROLES: readonly UserRole[] = ["rep", "manager", "admin"];

export const NAV_ITEMS: readonly NavItem[] = [
  { label: "Leads", path: "/leads", roles: ALL_ROLES },
  // M2 entries (M2-0): permissions mirror IMPORT_LEADS, FIX_QUARANTINE, REVIEW_DUPLICATES and
  // MANAGE_SOURCE_PROFILES in the backend; the server still enforces them.
  { label: "Import", path: "/leads/import", roles: ALL_ROLES },
  { label: "Quarantine", path: "/leads/quarantine", roles: ALL_ROLES },
  { label: "Duplicates", path: "/leads/duplicates", roles: ["manager", "admin"] },
  { label: "Campaigns", path: "/campaigns", roles: ALL_ROLES },
  { label: "Review", path: "/review", roles: ALL_ROLES },
  { label: "Outbox", path: "/outbox", roles: ALL_ROLES },
  { label: "Admin", path: "/admin", roles: ["admin"] },
  { label: "Source profiles", path: "/admin/source-profiles", roles: ["admin"] },
  { label: "Mappings", path: "/admin/mappings", roles: ["admin"] },
  { label: "Users", path: "/users", roles: ["admin"] },
  { label: "My profile", path: "/profile", roles: ALL_ROLES },
];
