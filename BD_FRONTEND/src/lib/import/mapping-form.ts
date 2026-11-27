/**
 * Pure helpers that turn the server's mapping columns into form state and back.
 *
 * Needed so the mapping table's logic (selection state, the PUT body, the "used twice" hint) is
 * testable without rendering. The hint is for the user only; the server still refuses a target
 * used by two columns (422) and remains the source of truth.
 */
import type { MappingColumnResponse, MappingEntry } from "@/lib/api/types.gen";

/** Chosen target per column index; null means "ignore this column". */
export type Selection = Record<number, string | null>;

/** Starts the form from the server's suggestion or saved mapping. */
export function selectionFromColumns(columns: MappingColumnResponse[]): Selection {
  return Object.fromEntries(columns.map((c) => [c.column_index, c.target_field]));
}

/** Body of `PUT /imports/{id}/mapping`: one entry per column. */
export function toEntries(selection: Selection): MappingEntry[] {
  return Object.entries(selection).map(([index, target]) => ({
    column_index: Number(index),
    target_field: target,
  }));
}

/** Target keys chosen by more than one column (UI hint only). */
export function duplicateTargets(selection: Selection): Set<string> {
  const seen = new Set<string>();
  const repeated = new Set<string>();
  for (const target of Object.values(selection)) {
    if (target === null) continue;
    if (seen.has(target)) repeated.add(target);
    seen.add(target);
  }
  return repeated;
}

/** Splits target fields into groups, keeping the server's order. */
export function groupFields<T extends { group: string }>(fields: T[]): [string, T[]][] {
  const groups = new Map<string, T[]>();
  for (const field of fields) {
    groups.set(field.group, [...(groups.get(field.group) ?? []), field]);
  }
  return [...groups.entries()];
}
