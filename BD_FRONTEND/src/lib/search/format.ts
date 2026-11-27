/**
 * Display helpers for the Leads search screen (task M3-A3).
 *
 * Needed so names, places, badge wording, sortable columns and error messages live in one tested
 * place instead of inside the components. Presentation only: the server decides which leads
 * match, which badges apply and who may search; nothing here checks a rule or a role.
 */
import type { Badge, SearchRow, SortField } from "@/lib/api/types.gen";

/** Results per page: the API's default page size, kept in step with `DEFAULT_PAGE_SIZE` there. */
export const PAGE_SIZE = 50;

/** Shown where a value is missing. */
export const EMPTY_CELL = "—";

export const BADGE_LABELS: Record<Badge, string> = {
  cooling_off: "Cooling off",
  replied: "Replied",
  possible_duplicate: "Possible duplicate",
  unverified_email: "Unverified email",
  opted_out: "Opted out",
};

/** Columns the user can sort by, with their header text (the API's `SortField` values). */
export const SORTABLE_COLUMNS: ReadonlyArray<{ field: SortField; label: string }> = [
  { field: "name", label: "Name" },
  { field: "title", label: "Title" },
  { field: "company", label: "Company" },
  { field: "last_contacted_at", label: "Last contacted" },
];

/** "First Last", or just the first name when there is no last name. */
export function displayName(row: Pick<SearchRow, "first_name" | "last_name">): string {
  return [row.first_name, row.last_name].filter(Boolean).join(" ");
}

/** The person's own place, falling back to the company headquarters, as "City, State, Country". */
export function displayLocation(row: SearchRow): string {
  const own = [row.city, row.state, row.country].filter(Boolean);
  const parts = own.length > 0 ? own : [row.company?.hq_city, row.company?.hq_state, row.company?.hq_country].filter(Boolean);
  return parts.length > 0 ? parts.join(", ") : EMPTY_CELL;
}

/** The date part of an ISO timestamp for the list, or a dash when never contacted. */
export function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : EMPTY_CELL;
}

/** The next sort order after the user clicks a header: the first click ascends, a repeat flips. */
export function nextSort(
  current: { field: SortField; direction: "asc" | "desc" },
  clicked: SortField,
): { field: SortField; direction: "asc" | "desc" } {
  if (current.field !== clicked) return { field: clicked, direction: "asc" };
  return { field: clicked, direction: current.direction === "asc" ? "desc" : "asc" };
}

/** Number of pages for `total` results (at least 1, so "page 1 of 1" shows when empty). */
export function pageCount(total: number): number {
  return Math.max(1, Math.ceil(total / PAGE_SIZE));
}

const MESSAGE_UNREACHABLE = "The server could not be reached. Check your connection and try again.";
const MESSAGE_FORBIDDEN = "You do not have permission to search leads.";
const MESSAGE_INVALID = "These filters are not valid together. Adjust them and try again.";
const MESSAGE_GENERIC = "The search failed. Try again, and tell an admin if it keeps happening.";

/** Plain-language text for a failed search, from the HTTP status (undefined = no answer). */
export function describeSearchFailure(status: number | undefined): string {
  if (status === undefined) return MESSAGE_UNREACHABLE;
  if (status === 403) return MESSAGE_FORBIDDEN;
  if (status === 422) return MESSAGE_INVALID;
  return MESSAGE_GENERIC;
}
