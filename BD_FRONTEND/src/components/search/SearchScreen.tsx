"use client";

/**
 * The Leads search screen (task M3-A3, milestone/m3.md section 19).
 *
 * Needed so BD can find leads by industry, size, place, title, technology, revenue, funding,
 * Salesforce use and status flags, and pick some or all of them (D-024, D-025, D-106). It joins
 * the filter panel, chips, results table, pager and selection bar. It decides nothing: the server
 * builds the query, hides opted-out leads by default and attaches the badges. Filters, order,
 * page and selection live in page state only; applying new filters clears the selection and
 * returns to page 1, so a stale "all matching" can never survive. The Export CSV button (M3-A5)
 * always exports the applied filters, whatever is ticked. The sentence box (M3-A6) only fills the
 * draft filters, so the user reviews and applies them like any other filter change.
 */
import { useState } from "react";

import ActiveFilterChips from "@/components/search/ActiveFilterChips";
import ExportButton from "@/components/search/ExportButton";
import FilterPanel from "@/components/search/FilterPanel";
import NlSearchBox from "@/components/search/NlSearchBox";
import Pagination from "@/components/search/Pagination";
import ResultsTable from "@/components/search/ResultsTable";
import SegmentPanel from "@/components/search/SegmentPanel";
import SelectionBar from "@/components/search/SelectionBar";
import styles from "@/components/search/search.module.css";
import type { SortDirection, SortField } from "@/lib/api/types.gen";
import { EMPTY_FILTERS, type FilterSet } from "@/lib/search/filters";
import { nextSort } from "@/lib/search/format";
import {
  NO_SELECTION,
  isPageSelected,
  selectAllMatching,
  toggleRow,
  togglePage,
  type Selection,
} from "@/lib/search/selection";
import { useFilterOptions, useSearchResults } from "@/lib/search/use-search";

/** Renders the whole search screen. */
export default function SearchScreen() {
  const options = useFilterOptions();
  const [draft, setDraft] = useState<FilterSet>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<FilterSet>(EMPTY_FILTERS);
  const [sort, setSort] = useState<{ field: SortField; direction: SortDirection }>({
    field: "name",
    direction: "asc",
  });
  const [offset, setOffset] = useState(0);
  const [reloadCount, setReloadCount] = useState(0);
  const [selection, setSelection] = useState<Selection>(NO_SELECTION);
  // Bumped when the NL box loads a draft, so the filter panel remounts and its typed revenue
  // boxes show the interpreted values.
  const [draftVersion, setDraftVersion] = useState(0);

  const { data, error, loading } = useSearchResults({
    filters: applied,
    sort: sort.field,
    direction: sort.direction,
    offset,
    reloadCount,
  });

  const rows = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageIds = rows.map((row) => row.person_id);

  /** Applies new filters: back to page 1 and drop the selection, which belonged to the old filters. */
  function applyFilters(next: FilterSet) {
    setDraft(next);
    setApplied(next);
    setOffset(0);
    setSelection(NO_SELECTION);
  }

  /** Loads AI-interpreted filters into the draft only; nothing is applied until "Apply filters". */
  function loadInterpretedDraft(next: FilterSet) {
    setDraft(next);
    setDraftVersion((version) => version + 1);
  }

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>Leads</h1>
          <p className={styles.subtitle}>
            Find leads, then tick the ones you want. Opted-out leads are hidden unless you ask for
            them.
          </p>
        </div>
        {data && (
          <div>
            <span className={styles.total}>{total} leads match</span>
            <ExportButton
              filters={applied}
              sort={sort.field}
              direction={sort.direction}
              disabled={total === 0}
            />
          </div>
        )}
      </header>

      <div className={styles.layout}>
        <aside className={styles.sidebar}>
          {/* Sentence search (M3-A6): fills the draft filters below; the user still presses Apply. */}
          <NlSearchBox onInterpreted={loadInterpretedDraft} />

          {/* Saves the applied filters; applying a segment is the same as pressing Apply (page 1, no selection). */}
      <SegmentPanel filters={applied} onApply={applyFilters} />

      {/* Remounted when an applied revenue changes, so its typed text follows a removed chip. */}
          <FilterPanel
            key={`${applied.revenue_min ?? ""}|${applied.revenue_max ?? ""}|${draftVersion}`}
            draft={draft}
            options={options}
            onChange={setDraft}
            onApply={applyFilters}
            onClear={() => applyFilters(EMPTY_FILTERS)}
          />
        </aside>

        <div className={styles.results}>
          <ActiveFilterChips filters={applied} onChange={applyFilters} />

          {error && (
            <p className={styles.notice} role="alert">
              {error}
              <button
                className={styles.secondary}
                type="button"
                onClick={() => setReloadCount((count) => count + 1)}
              >
                Retry
              </button>
            </p>
          )}
          {loading && (
            <p className={styles.state} aria-live="polite">
              Loading…
            </p>
          )}
          {!loading && data && rows.length === 0 && (
            <p className={styles.state}>No leads match these filters.</p>
          )}

          {rows.length > 0 && (
            <>
              <SelectionBar
                selection={selection}
                total={total}
                pageFullySelected={isPageSelected(selection, pageIds)}
                onSelectAllMatching={() => setSelection(selectAllMatching(applied))}
                onClear={() => setSelection(NO_SELECTION)}
              />
              <ResultsTable
                rows={rows}
                selection={selection}
                sort={sort.field}
                direction={sort.direction}
                onToggleRow={(id) => setSelection((current) => toggleRow(current, id))}
                onTogglePage={() => setSelection((current) => togglePage(current, pageIds))}
                onSort={(field) => {
                  setSort((current) => nextSort(current, field));
                  setOffset(0);
                }}
              />
              <Pagination offset={offset} total={total} onOffsetChange={setOffset} />
            </>
          )}
        </div>
      </div>
    </section>
  );
}
