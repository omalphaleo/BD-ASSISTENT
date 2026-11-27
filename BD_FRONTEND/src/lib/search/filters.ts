/**
 * Filter state helpers for the Leads search screen (task M3-A3).
 *
 * Needed so the filter panel, the active-filter chips and the "Apply" button share one tested
 * description of a `FilterSet`: how a value is toggled, which combinations the server refuses and
 * what each active filter is called. The server stays the authority (it answers 422 for a bad
 * combination); the rules here only stop the user from building one by accident (D-106).
 */
import type { FilterSetInput, LeadStatusFlagType, SizeBand } from "@/lib/api/types.gen";

/**
 * The filter object the screen builds and sends. Since saved segments (M3-A4) the API schema is
 * both a request and a response, so the generator names it `FilterSetInput` and `FilterSetOutput`;
 * the screen keeps one name for it here. A segment's saved filters (the output form) are
 * assignable to it, because the output only adds fields the input already allows.
 */
export type FilterSet = FilterSetInput;

/** The filter fields that hold a list of text values. */
export type ListField =
  | "industries"
  | "company_names"
  | "countries"
  | "states"
  | "cities"
  | "titles"
  | "technologies"
  | "funding_stages";

/** How a status flag takes part in a search: not used, required (any of) or excluded. */
export type FlagMode = "any" | "include" | "exclude";

/** One removable chip: a label to show and the filter value it stands for. */
export type FilterChip = Readonly<{ key: string; label: string; remove: (f: FilterSet) => FilterSet }>;

/** A search with no filter: the server's default view (every lead except opted-out ones). */
export const EMPTY_FILTERS: FilterSet = {};

export const SIZE_BAND_LABELS: Record<SizeBand, string> = {
  smb: "SMB (1–200)",
  mid_market: "Mid-market (201–1,000)",
  enterprise: "Enterprise (1,000+)",
};

export const FLAG_LABELS: Record<LeadStatusFlagType, string> = {
  existing_customer: "Existing customer",
  in_conversation: "In conversation",
  partner: "Partner",
  competitor: "Competitor",
  qualified: "Qualified",
  handed_off_to_sales: "Handed off to sales",
};

const LIST_FIELD_LABELS: Record<ListField, string> = {
  industries: "Industry",
  company_names: "Company",
  countries: "Country",
  states: "State",
  cities: "City",
  titles: "Title",
  technologies: "Technology",
  funding_stages: "Funding",
};

/** Returns the list with `value` added, or removed when it is already there. */
export function toggleInList<T>(list: readonly T[], value: T): T[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

/** Reads a text-list field, treating a missing field as an empty list. */
export function listValues(filters: FilterSet, field: ListField): string[] {
  return filters[field] ?? [];
}

/** Returns new filters with `value` toggled in a text-list field. */
export function toggleListValue(filters: FilterSet, field: ListField, value: string): FilterSet {
  return { ...filters, [field]: toggleInList(listValues(filters, field), value) };
}

/** Returns new filters with `term` added to a free-text field; blank or repeated terms are ignored. */
export function addTerm(filters: FilterSet, field: "titles" | "company_names", term: string): FilterSet {
  const clean = term.trim();
  if (clean === "" || listValues(filters, field).includes(clean)) return filters;
  return { ...filters, [field]: [...listValues(filters, field), clean] };
}

/** Returns new filters with a company size band toggled. */
export function toggleSizeBand(filters: FilterSet, band: SizeBand): FilterSet {
  return { ...filters, size_bands: toggleInList(filters.size_bands ?? [], band) };
}

/** Says how one flag currently takes part in the search. */
export function flagMode(filters: FilterSet, flag: LeadStatusFlagType): FlagMode {
  if (filters.flags_include?.includes(flag)) return "include";
  if (filters.flags_exclude?.includes(flag)) return "exclude";
  return "any";
}

/**
 * Sets a flag to "any", "include" or "exclude". A flag is removed from the other list first so it
 * is never in both, which the server rejects.
 */
export function setFlagMode(filters: FilterSet, flag: LeadStatusFlagType, mode: FlagMode): FilterSet {
  const include = (filters.flags_include ?? []).filter((item) => item !== flag);
  const exclude = (filters.flags_exclude ?? []).filter((item) => item !== flag);
  if (mode === "include") include.push(flag);
  if (mode === "exclude") exclude.push(flag);
  return { ...filters, flags_include: include, flags_exclude: exclude };
}

/** Turns "Eligible only" on or off; turning it on turns "Show opted-out" off (the server refuses both). */
export function setEligibleOnly(filters: FilterSet, on: boolean): FilterSet {
  return { ...filters, eligible_only: on, show_opted_out: on ? false : filters.show_opted_out };
}

/** Turns "Show opted-out" on or off; turning it on turns "Eligible only" off (the server refuses both). */
export function setShowOptedOut(filters: FilterSet, on: boolean): FilterSet {
  return { ...filters, show_opted_out: on, eligible_only: on ? false : filters.eligible_only };
}

/** Parses a revenue input: blank means "no limit"; anything that is not a number >= 0 is invalid. */
export function parseRevenue(text: string): number | null | "invalid" {
  const clean = text.trim();
  if (clean === "") return null;
  const value = Number(clean);
  return Number.isFinite(value) && value >= 0 ? value : "invalid";
}

/** Explains why revenue inputs cannot be applied, or returns null when they can. */
export function revenueError(minText: string, maxText: string): string | null {
  const min = parseRevenue(minText);
  const max = parseRevenue(maxText);
  if (min === "invalid" || max === "invalid") return "Revenue must be a number of 0 or more.";
  if (min !== null && max !== null && min > max) return "Minimum revenue must not exceed maximum revenue.";
  return null;
}

/** Builds the removable chips for every filter that is switched on, in a stable order. */
export function activeChips(filters: FilterSet): FilterChip[] {
  const chips: FilterChip[] = [];
  (Object.keys(LIST_FIELD_LABELS) as ListField[]).forEach((field) => {
    listValues(filters, field).forEach((value) => {
      chips.push({
        key: `${field}:${value}`,
        label: `${LIST_FIELD_LABELS[field]}: ${value}`,
        remove: (f) => toggleListValue(f, field, value),
      });
    });
  });
  (filters.size_bands ?? []).forEach((band) => {
    chips.push({
      key: `size:${band}`,
      label: `Size: ${SIZE_BAND_LABELS[band]}`,
      remove: (f) => toggleSizeBand(f, band),
    });
  });
  if (filters.uses_salesforce !== null && filters.uses_salesforce !== undefined) {
    chips.push({
      key: "salesforce",
      label: filters.uses_salesforce ? "Uses Salesforce" : "Does not use Salesforce",
      remove: (f) => ({ ...f, uses_salesforce: null }),
    });
  }
  if (filters.revenue_min !== null && filters.revenue_min !== undefined) {
    chips.push({
      key: "revenue_min",
      label: `Revenue from ${filters.revenue_min}`,
      remove: (f) => ({ ...f, revenue_min: null }),
    });
  }
  if (filters.revenue_max !== null && filters.revenue_max !== undefined) {
    chips.push({
      key: "revenue_max",
      label: `Revenue up to ${filters.revenue_max}`,
      remove: (f) => ({ ...f, revenue_max: null }),
    });
  }
  (filters.flags_include ?? []).forEach((flag) => {
    chips.push({
      key: `flag+:${flag}`,
      label: `Flag: ${FLAG_LABELS[flag]}`,
      remove: (f) => setFlagMode(f, flag, "any"),
    });
  });
  (filters.flags_exclude ?? []).forEach((flag) => {
    chips.push({
      key: `flag-:${flag}`,
      label: `Not flagged: ${FLAG_LABELS[flag]}`,
      remove: (f) => setFlagMode(f, flag, "any"),
    });
  });
  if (filters.eligible_only) {
    chips.push({ key: "eligible_only", label: "Eligible only", remove: (f) => setEligibleOnly(f, false) });
  }
  if (filters.show_opted_out) {
    chips.push({ key: "show_opted_out", label: "Showing opted-out", remove: (f) => setShowOptedOut(f, false) });
  }
  return chips;
}
