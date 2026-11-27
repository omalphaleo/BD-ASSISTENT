"use client";

/**
 * A collapsible filter section holding a list of checkboxes (task M3-A3).
 *
 * Needed because filter values such as cities or technologies can number in the hundreds: the
 * section folds away, shows how many values are ticked, scrolls inside a fixed height and has a
 * small search box that narrows what is shown without changing what is ticked. When the server cut
 * the list off (`truncated`), a note says so, because values missing here cannot be picked.
 * Holds no rule.
 */
import { useState } from "react";

import styles from "@/components/search/search.module.css";

type Option = Readonly<{ value: string; label: string }>;

/** Renders one section: a header button (title, ticked count) and, when open, the checkboxes. */
export default function CheckboxGroup({
  title,
  options,
  selected,
  onToggle,
  truncated = false,
  defaultOpen = false,
}: Readonly<{
  title: string;
  options: readonly Option[];
  selected: readonly string[];
  onToggle: (value: string) => void;
  truncated?: boolean;
  defaultOpen?: boolean;
}>) {
  const [open, setOpen] = useState(defaultOpen || selected.length > 0);
  const [query, setQuery] = useState("");
  if (options.length === 0) return null;

  const needle = query.trim().toLowerCase();
  const shown = needle ? options.filter((o) => o.label.toLowerCase().includes(needle)) : options;

  return (
    <section className={styles.section}>
      <button
        type="button"
        className={styles.sectionButton}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span>
          {title}
          {selected.length > 0 && <span className={styles.count}>{selected.length}</span>}
        </span>
        <span className={`${styles.chevron} ${open ? styles.chevronOpen : ""}`} aria-hidden="true">
          ▶
        </span>
      </button>
      {open && (
        <div className={styles.sectionBody}>
          {options.length > 8 && (
            <input
              type="search"
              className={styles.searchInput}
              aria-label={`Search ${title}`}
              placeholder={`Search ${title.toLowerCase()}…`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          )}
          <div className={styles.optionList} role="group" aria-label={title}>
            {shown.map((option) => (
              <label key={option.value} className={styles.option}>
                <input
                  type="checkbox"
                  checked={selected.includes(option.value)}
                  onChange={() => onToggle(option.value)}
                />
                <span>{option.label}</span>
              </label>
            ))}
            {shown.length === 0 && <span className={styles.hint}>No match.</span>}
          </div>
          {truncated && (
            <p className={styles.hint}>
              Showing the first {options.length} values only; some are not listed.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
