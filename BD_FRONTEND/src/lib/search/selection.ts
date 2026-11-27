/**
 * Selection state for the Leads search screen (task M3-A3, decision: page state only).
 *
 * Needed so "select all matching" stores the FILTER, not a list of lead IDs, and the lead set is
 * resolved only when a campaign is made (M4), so the count can never go stale (m3.md section 5).
 * A selection is either a set of chosen row IDs or "all leads matching these filters". Pure
 * functions with no API calls; the screen clears the selection whenever the filters change.
 */
import type { FilterSet } from "@/lib/search/filters";

/** Either specific leads or every lead that matches `filters` (resolved later by the server). */
export type Selection =
  | Readonly<{ kind: "rows"; ids: ReadonlySet<string> }>
  | Readonly<{ kind: "all"; filters: FilterSet }>;

/** Nothing selected. */
export const NO_SELECTION: Selection = { kind: "rows", ids: new Set() };

/** True when the lead is part of the selection (in "all matching" mode every row is). */
export function isSelected(selection: Selection, personId: string): boolean {
  return selection.kind === "all" || selection.ids.has(personId);
}

/**
 * Ticks or unticks one row. In "all matching" mode this does nothing: the selection cannot
 * express exceptions, so the user must clear it first.
 */
export function toggleRow(selection: Selection, personId: string): Selection {
  if (selection.kind === "all") return selection;
  const ids = new Set(selection.ids);
  if (ids.has(personId)) ids.delete(personId);
  else ids.add(personId);
  return { kind: "rows", ids };
}

/** True when every listed row is already selected (used for the "select page" checkbox). */
export function isPageSelected(selection: Selection, pageIds: readonly string[]): boolean {
  return pageIds.length > 0 && pageIds.every((id) => isSelected(selection, id));
}

/** Selects every row on the page, or unselects them all when they were already selected. */
export function togglePage(selection: Selection, pageIds: readonly string[]): Selection {
  if (selection.kind === "all") return selection;
  const ids = new Set(selection.ids);
  const allSelected = isPageSelected(selection, pageIds);
  pageIds.forEach((id) => (allSelected ? ids.delete(id) : ids.add(id)));
  return { kind: "rows", ids };
}

/** Selects every lead matching the filters, by keeping the filters themselves. */
export function selectAllMatching(filters: FilterSet): Selection {
  return { kind: "all", filters };
}

/** How many leads are selected: the number of chosen rows, or the server's total for "all". */
export function selectedCount(selection: Selection, total: number): number {
  return selection.kind === "all" ? total : selection.ids.size;
}
