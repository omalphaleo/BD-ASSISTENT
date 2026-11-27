/**
 * Unit tests for the pure search helpers (task M3-A3).
 *
 * Needed so the filter rules (no flag both included and excluded, eligible-only versus
 * show-opted-out, revenue checks), the selection rules ("all matching" keeps the filter, not IDs)
 * and the display and sort helpers cannot regress unnoticed. No component is rendered and no
 * request is made; all data is synthetic.
 */
import { describe, expect, it } from "vitest";

import {
  activeChips,
  addTerm,
  flagMode,
  revenueError,
  setEligibleOnly,
  setFlagMode,
  setShowOptedOut,
  toggleListValue,
  toggleSizeBand,
} from "@/lib/search/filters";
import {
  EMPTY_CELL,
  describeSearchFailure,
  displayLocation,
  displayName,
  nextSort,
  pageCount,
} from "@/lib/search/format";
import {
  NO_SELECTION,
  isPageSelected,
  isSelected,
  selectAllMatching,
  selectedCount,
  toggleRow,
  togglePage,
} from "@/lib/search/selection";
import type { SearchRow } from "@/lib/api/types.gen";

describe("filters", () => {
  it("toggling a list value adds it, and toggling again removes it", () => {
    const added = toggleListValue({}, "industries", "Pharma");
    expect(added.industries).toEqual(["Pharma"]);
    expect(toggleListValue(added, "industries", "Pharma").industries).toEqual([]);
  });

  it("adding a blank or repeated term leaves the filters unchanged", () => {
    const once = addTerm({}, "titles", "  CFO ");
    expect(once.titles).toEqual(["CFO"]);
    expect(addTerm(once, "titles", "CFO")).toBe(once);
    expect(addTerm(once, "titles", "   ")).toBe(once);
  });

  it("setting a flag to include then exclude never leaves it in both lists", () => {
    const included = setFlagMode({}, "qualified", "include");
    expect(flagMode(included, "qualified")).toBe("include");
    const excluded = setFlagMode(included, "qualified", "exclude");
    expect(excluded.flags_include).toEqual([]);
    expect(excluded.flags_exclude).toEqual(["qualified"]);
    expect(flagMode(setFlagMode(excluded, "qualified", "any"), "qualified")).toBe("any");
  });

  it("turning on eligible-only turns off show-opted-out, and the reverse", () => {
    const eligible = setEligibleOnly({ show_opted_out: true }, true);
    expect(eligible).toMatchObject({ eligible_only: true, show_opted_out: false });
    const opted = setShowOptedOut(eligible, true);
    expect(opted).toMatchObject({ eligible_only: false, show_opted_out: true });
  });

  it("revenue: blank is fine, a non-number or a reversed range gives a message", () => {
    expect(revenueError("", "")).toBeNull();
    expect(revenueError("100", "500")).toBeNull();
    expect(revenueError("abc", "")).toMatch(/number/);
    expect(revenueError("-5", "")).toMatch(/number/);
    expect(revenueError("900", "100")).toMatch(/must not exceed/);
  });

  it("each applied filter becomes a chip, and removing a chip clears only that filter", () => {
    const filters = toggleSizeBand(toggleListValue({ uses_salesforce: true }, "cities", "Pune"), "smb");
    const chips = activeChips(filters);
    expect(chips.map((chip) => chip.label)).toEqual([
      "City: Pune",
      "Size: SMB (1–200)",
      "Uses Salesforce",
    ]);
    const withoutCity = chips[0].remove(filters);
    expect(withoutCity.cities).toEqual([]);
    expect(withoutCity.size_bands).toEqual(["smb"]);
  });

  it("no filters means no chips", () => {
    expect(activeChips({})).toEqual([]);
  });
});

describe("selection", () => {
  it("toggling a row selects it and toggling again unselects it", () => {
    const one = toggleRow(NO_SELECTION, "a");
    expect(isSelected(one, "a")).toBe(true);
    expect(selectedCount(one, 100)).toBe(1);
    expect(isSelected(toggleRow(one, "a"), "a")).toBe(false);
  });

  it("select page selects every row, and a second toggle clears them", () => {
    const page = ["a", "b", "c"];
    const all = togglePage(NO_SELECTION, page);
    expect(isPageSelected(all, page)).toBe(true);
    expect(selectedCount(all, 100)).toBe(3);
    expect(isPageSelected(togglePage(all, page), page)).toBe(false);
  });

  it("select all matching keeps the filters, counts the server total and ignores row toggles", () => {
    const filters = { industries: ["Pharma"] };
    const all = selectAllMatching(filters);
    expect(all).toEqual({ kind: "all", filters });
    expect(selectedCount(all, 321)).toBe(321);
    expect(isSelected(all, "any-id")).toBe(true);
    expect(toggleRow(all, "a")).toBe(all);
  });

  it("an empty page is never reported as fully selected", () => {
    expect(isPageSelected(NO_SELECTION, [])).toBe(false);
  });
});

describe("format", () => {
  const row = {
    first_name: "Asha",
    last_name: null,
    city: null,
    state: null,
    country: null,
    company: { hq_city: "Pune", hq_state: null, hq_country: "India" },
  } as unknown as SearchRow;

  it("name drops a missing last name, and location falls back to the company headquarters", () => {
    expect(displayName(row)).toBe("Asha");
    expect(displayLocation(row)).toBe("Pune, India");
    expect(displayLocation({ ...row, company: null })).toBe(EMPTY_CELL);
  });

  it("clicking a new column sorts it ascending; clicking it again flips the direction", () => {
    expect(nextSort({ field: "name", direction: "asc" }, "company")).toEqual({
      field: "company",
      direction: "asc",
    });
    expect(nextSort({ field: "name", direction: "asc" }, "name").direction).toBe("desc");
    expect(nextSort({ field: "name", direction: "desc" }, "name").direction).toBe("asc");
  });

  it("page count is at least 1 and rounds up", () => {
    expect(pageCount(0)).toBe(1);
    expect(pageCount(50)).toBe(1);
    expect(pageCount(51)).toBe(2);
  });

  it("failure messages cover no answer, 403, 422 and anything else", () => {
    expect(describeSearchFailure(undefined)).toMatch(/could not be reached/);
    expect(describeSearchFailure(403)).toMatch(/permission/);
    expect(describeSearchFailure(422)).toMatch(/not valid together/);
    expect(describeSearchFailure(500)).toMatch(/search failed/);
  });
});
