/**
 * Unit tests for the pure mapping-form helpers (task M2-A2 UI).
 *
 * Needed so the PUT body, the "used twice" hint and the field grouping cannot regress. No
 * rendering and no API calls; the data is synthetic.
 */
import { describe, expect, it } from "vitest";

import {
  duplicateTargets,
  groupFields,
  selectionFromColumns,
  toEntries,
} from "@/lib/import/mapping-form";

const COLUMNS = [
  { column_index: 0, source_header: "Email", target_field: "email", origin: "builtin", is_reassigned: false },
  { column_index: 1, source_header: "", target_field: null, origin: "unmapped", is_reassigned: false },
];

describe("mapping-form", () => {
  it("selection round trip: columns become a selection and then PUT entries", () => {
    const selection = selectionFromColumns(COLUMNS);

    expect(selection).toEqual({ 0: "email", 1: null });
    expect(toEntries(selection)).toEqual([
      { column_index: 0, target_field: "email" },
      { column_index: 1, target_field: null },
    ]);
  });

  it("duplicateTargets: reports a field chosen twice and ignores ignored columns", () => {
    expect([...duplicateTargets({ 0: "email", 1: "email", 2: null, 3: null })]).toEqual(["email"]);
    expect(duplicateTargets({ 0: "email", 1: null }).size).toBe(0);
  });

  it("groupFields: keeps the server order inside each group", () => {
    const grouped = groupFields([
      { key: "a", group: "person" },
      { key: "b", group: "email" },
      { key: "c", group: "person" },
    ]);

    expect(grouped.map(([group]) => group)).toEqual(["person", "email"]);
    expect(grouped[0][1].map((f) => f.key)).toEqual(["a", "c"]);
  });
});
