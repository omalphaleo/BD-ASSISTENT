"use client";

/**
 * Previous and Next buttons with a "page X of Y" label (task M3-A3).
 *
 * Needed because search returns 50 leads at a time (offset paging, as the API defines it).
 * Holds no rule; the screen supplies the offset and total and decides what a click does.
 */
import styles from "@/components/search/search.module.css";
import { PAGE_SIZE, pageCount } from "@/lib/search/format";

/** Renders the pager; each button disables at its end. */
export default function Pagination({
  offset,
  total,
  onOffsetChange,
}: Readonly<{ offset: number; total: number; onOffsetChange: (next: number) => void }>) {
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  return (
    <nav className={styles.pager} aria-label="Pages">
      <span className={styles.total}>
        Page {page} of {pageCount(total)} · {total} leads
      </span>
      <div className={styles.pagerButtons}>
        <button
          className={styles.secondary}
          type="button"
          disabled={offset === 0}
          onClick={() => onOffsetChange(Math.max(0, offset - PAGE_SIZE))}
        >
          Previous
        </button>
        <button
          className={styles.secondary}
          type="button"
          disabled={offset + PAGE_SIZE >= total}
          onClick={() => onOffsetChange(offset + PAGE_SIZE)}
        >
          Next
        </button>
      </div>
    </nav>
  );
}
