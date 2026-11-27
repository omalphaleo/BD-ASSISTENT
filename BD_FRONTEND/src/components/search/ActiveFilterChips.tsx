"use client";

/**
 * The row of chips showing which filters the current results use (task M3-A3).
 *
 * Needed so a rep can see at a glance why a list looks the way it does and drop one filter with
 * one click instead of hunting through the panel. Shows only applied filters; holds no rule.
 */
import styles from "@/components/search/search.module.css";
import { activeChips, type FilterSet } from "@/lib/search/filters";

/** Renders one removable chip per applied filter, or nothing when no filter is applied. */
export default function ActiveFilterChips({
  filters,
  onChange,
}: Readonly<{ filters: FilterSet; onChange: (next: FilterSet) => void }>) {
  const chips = activeChips(filters);
  if (chips.length === 0) return null;
  return (
    <ul className={styles.chips} aria-label="Active filters">
      {chips.map((chip) => (
        <li key={chip.key}>
          <button
            type="button"
            className={styles.chip}
            aria-label={`Remove filter ${chip.label}`}
            onClick={() => onChange(chip.remove(filters))}
          >
            {chip.label} <span className={styles.chipRemove}>✕</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
