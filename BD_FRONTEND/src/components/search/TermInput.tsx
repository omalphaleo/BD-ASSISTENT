"use client";

/**
 * A filter section with a text box that adds search terms one at a time (task M3-A3).
 *
 * Needed for the free-text filters (job title, company name), which the server matches by
 * "contains" and which have no list of values to tick. Added terms appear as removable chips.
 * Holds no rule; the parent decides what to do with the list.
 */
import { useState } from "react";

import styles from "@/components/search/search.module.css";

/** Renders the box with an Add button and the terms added so far. */
export default function TermInput({
  label,
  terms,
  onAdd,
  onRemove,
}: Readonly<{
  label: string;
  terms: readonly string[];
  onAdd: (term: string) => void;
  onRemove: (term: string) => void;
}>) {
  const [text, setText] = useState("");

  function add() {
    if (text.trim() === "") return;
    onAdd(text);
    setText("");
  }

  return (
    <section className={styles.section}>
      <div className={styles.sectionBody} style={{ paddingTop: 12 }}>
        <label className={styles.fieldLabel}>
          <span>{label}</span>
          <span className={styles.termRow}>
            <input
              type="text"
              className={styles.input}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault(); // Enter adds the term; it must not submit the surrounding form
                  add();
                }
              }}
            />
            <button type="button" className={styles.secondary} onClick={add}>
              Add {label.toLowerCase()}
            </button>
          </span>
        </label>
        {terms.length > 0 && (
          <div className={styles.chipRow}>
            {terms.map((term) => (
              <button
                key={term}
                type="button"
                className={styles.chip}
                aria-label={`Remove ${label.toLowerCase()} ${term}`}
                onClick={() => onRemove(term)}
              >
                {term} <span className={styles.chipRemove}>✕</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
