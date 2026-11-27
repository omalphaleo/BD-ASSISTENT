"use client";

/**
 * The results table of the Leads search screen (task M3-A3).
 *
 * Needed so BD can scan leads, sort them, tick the ones they want and open a lead. Each name
 * links to /leads/{personId} by path only (the lead page belongs to the other workstream,
 * m3.md section 18). Every value is rendered as React text, never as HTML. The table scrolls
 * sideways inside its card on narrow screens instead of breaking the page layout.
 */
import Link from "next/link";

import BadgeList from "@/components/search/BadgeList";
import styles from "@/components/search/search.module.css";
import type { SearchRow, SortDirection, SortField } from "@/lib/api/types.gen";
import {
  EMPTY_CELL,
  SORTABLE_COLUMNS,
  displayLocation,
  displayName,
  formatDate,
} from "@/lib/search/format";
import { isPageSelected, isSelected, type Selection } from "@/lib/search/selection";

const COLUMN_LABEL = new Map(SORTABLE_COLUMNS.map((column) => [column.field, column.label]));

/** Renders the header (sort buttons and the select-page box) and one row per lead. */
export default function ResultsTable({
  rows,
  selection,
  sort,
  direction,
  onToggleRow,
  onTogglePage,
  onSort,
}: Readonly<{
  rows: readonly SearchRow[];
  selection: Selection;
  sort: SortField;
  direction: SortDirection;
  onToggleRow: (personId: string) => void;
  onTogglePage: () => void;
  onSort: (field: SortField) => void;
}>) {
  const allMatching = selection.kind === "all";
  const pageIds = rows.map((row) => row.person_id);

  function sortableHeader(field: SortField) {
    const active = sort === field;
    const label = COLUMN_LABEL.get(field) ?? field;
    return (
      <th
        scope="col"
        aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}
      >
        <button
          type="button"
          className={`${styles.sortButton} ${active ? styles.sortActive : ""}`}
          onClick={() => onSort(field)}
        >
          {label}
          {active ? (direction === "asc" ? " ▲" : " ▼") : ""}
        </button>
      </th>
    );
  }

  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption className="visually-hidden">Leads matching the filters</caption>
        <thead>
          <tr>
            <th scope="col" className={styles.checkCell}>
              <input
                type="checkbox"
                aria-label="Select all leads on this page"
                checked={isPageSelected(selection, pageIds)}
                disabled={allMatching}
                onChange={onTogglePage}
              />
            </th>
            {sortableHeader("name")}
            {sortableHeader("title")}
            {sortableHeader("company")}
            <th scope="col">Location</th>
            <th scope="col">Email</th>
            <th scope="col">Owner</th>
            {sortableHeader("last_contacted_at")}
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const name = displayName(row);
            return (
              <tr key={row.person_id} className={isSelected(selection, row.person_id) ? styles.rowSelected : undefined}>
                <td className={styles.checkCell}>
                  <input
                    type="checkbox"
                    aria-label={`Select ${name}`}
                    checked={isSelected(selection, row.person_id)}
                    disabled={allMatching}
                    onChange={() => onToggleRow(row.person_id)}
                  />
                </td>
                <td>
                  <Link className={styles.link} href={`/leads/${row.person_id}`}>
                    {name}
                  </Link>
                </td>
                <td>{row.title ?? EMPTY_CELL}</td>
                <td>{row.company?.name ?? EMPTY_CELL}</td>
                <td>{displayLocation(row)}</td>
                <td>{row.primary_email?.address ?? EMPTY_CELL}</td>
                <td className={row.owner ? undefined : styles.dim}>{row.owner?.name ?? "Unassigned"}</td>
                <td className={row.last_contacted_at ? undefined : styles.dim}>
                  {formatDate(row.last_contacted_at)}
                </td>
                <td>
                  <BadgeList badges={row.badges} flags={row.flags} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
