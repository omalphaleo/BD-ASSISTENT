"use client";

/**
 * The bar above the results showing what is selected (task M3-A3).
 *
 * Needed so BD sees how many leads are chosen, can widen the choice to every lead matching the
 * filters (the filter is kept, not a list of leads, so the count is never stale) and sees that
 * "Add to campaign" arrives with M4. Holds no rule.
 */
import styles from "@/components/search/search.module.css";
import { selectedCount, type Selection } from "@/lib/search/selection";

/** Renders the count, the select-all-matching and clear buttons, and the disabled campaign button. */
export default function SelectionBar({
  selection,
  total,
  pageFullySelected,
  onSelectAllMatching,
  onClear,
}: Readonly<{
  selection: Selection;
  total: number;
  pageFullySelected: boolean;
  onSelectAllMatching: () => void;
  onClear: () => void;
}>) {
  const count = selectedCount(selection, total);
  const canWiden = selection.kind === "rows" && pageFullySelected && count < total;
  return (
    <div
      className={`${styles.selectionBar} ${count > 0 ? styles.selectionBarActive : ""}`}
      role="status"
    >
      <span className={styles.selectionText}>
        {count} selected
        {selection.kind === "all" ? " (every lead matching the filters)" : ""}
      </span>
      {canWiden && (
        <button className={styles.secondary} type="button" onClick={onSelectAllMatching}>
          Select all {total} matching
        </button>
      )}
      {count > 0 && (
        <button className={styles.secondary} type="button" onClick={onClear}>
          Clear selection
        </button>
      )}
      <button
        className={styles.primary}
        style={{ flex: "none" }}
        type="button"
        disabled
        title="Available when campaigns arrive in M4"
      >
        Add to campaign
      </button>
    </div>
  );
}
