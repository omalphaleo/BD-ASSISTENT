"use client";

/**
 * The natural-language search box of the Leads screen (task M3-A6, plan section 9).
 *
 * Needed so BD can type "CFOs at pharma companies in Karnataka" instead of ticking filters. It
 * never runs a search: the interpreted filters are loaded into the filter panel as an unapplied
 * draft, so the user sees and edits them and then presses the usual "Apply filters". Anything the
 * app could not use is listed under the box. If the AI is off or fails, a plain message appears
 * and everything else on the screen keeps working. It holds no business rule: the server proposes
 * and validates the filters.
 */
import { useId, useState } from "react";

import styles from "@/components/search/search.module.css";
import type { FilterSet } from "@/lib/search/filters";
import {
  MAX_NL_QUERY_LENGTH,
  describeNotices,
  interpretQuery,
  isInterpretable,
} from "@/lib/search/nl-search";

type Props = Readonly<{
  /** Receives the interpreted filters; the screen puts them in the draft, unapplied. */
  onInterpreted: (filters: FilterSet) => void;
}>;

/** Renders the sentence input, the Interpret button and what happened. */
export default function NlSearchBox({ onInterpreted }: Props) {
  const inputId = useId();
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [notices, setNotices] = useState<string[] | null>(null);

  async function interpret() {
    setBusy(true);
    setFailure(null);
    setNotices(null);
    const outcome = await interpretQuery(query);
    setBusy(false);
    if (!outcome.ok) {
      setFailure(outcome.message);
      return;
    }
    onInterpreted(outcome.filters);
    setNotices(describeNotices(outcome.droppedFields, outcome.unrecognisedTerms));
  }

  return (
    <section className={styles.panel} aria-label="Search by sentence">
      <div className={styles.panelHead}>
        <strong>Search by sentence</strong>
      </div>
      <div className={styles.panelBody}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (isInterpretable(query) && !busy) void interpret();
          }}
        >
          <label className={styles.fieldLabel} htmlFor={inputId}>
            Describe who you are looking for
            <input
              id={inputId}
              type="text"
              className={styles.input}
              placeholder="CFOs at pharma companies in Karnataka"
              maxLength={MAX_NL_QUERY_LENGTH}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <button
            type="submit"
            className={styles.secondary}
            disabled={busy || !isInterpretable(query)}
          >
            {busy ? "Interpreting…" : "Interpret"}
          </button>
        </form>

        {failure && (
          <p className={styles.notice} role="alert">
            {failure}
          </p>
        )}
        {notices && (
          <div aria-live="polite">
            <p className={styles.hint}>
              Filters filled in below. Check them, edit if needed, then press Apply filters.
            </p>
            {notices.map((line) => (
              <p key={line} className={styles.hint}>
                {line}
              </p>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
