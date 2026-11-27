"use client";

/**
 * Data loading hooks for the Leads search screen (task M3-A3).
 *
 * Needed so the screen only describes what it wants (filters, order, page) and gets back the
 * rows, the total and a loading or error state. Calls the generated API client; holds no rule.
 * A stale answer (the user changed a filter while it was loading) is thrown away, the same way
 * the Quarantine screen does it.
 */
import { useEffect, useState } from "react";

import { getFilterOptionsSearchFilterOptionsGet, searchLeadsSearchLeadsPost } from "@/lib/api/sdk.gen";
import type {
  FilterOptionsResponse,
  SearchResponse,
  SortDirection,
  SortField,
} from "@/lib/api/types.gen";
import type { FilterSet } from "@/lib/search/filters";
import { PAGE_SIZE, describeSearchFailure } from "@/lib/search/format";

/** What to search for and which page to show. */
export type SearchQuery = Readonly<{
  filters: FilterSet;
  sort: SortField;
  direction: SortDirection;
  offset: number;
  /** Bumped by the screen to force a reload with the same query (the "Retry" button). */
  reloadCount: number;
}>;

type Loaded = Readonly<{ key: string; data: SearchResponse | null; error: string | null }>;

/**
 * Loads one page of results whenever the query changes.
 *
 * Returns the current page (null until the first answer), the error text of the latest request
 * (null when it worked) and whether the data on screen is out of date.
 */
export function useSearchResults(query: SearchQuery) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const key = JSON.stringify(query);

  useEffect(() => {
    let cancelled = false;
    // `query` is a new object on every render, so the effect depends on its serialized `key`
    // alone (otherwise it would re-run, and re-send the search, after every render). The query
    // is read back from the key so the effect uses exactly what the key describes.
    const current = JSON.parse(key) as SearchQuery;
    async function load() {
      const result = await searchLeadsSearchLeadsPost({
        body: {
          filters: current.filters,
          sort: current.sort,
          direction: current.direction,
          limit: PAGE_SIZE,
          offset: current.offset,
        },
      });
      if (cancelled) return; // a newer request replaced this one
      setLoaded({
        key,
        data: result.data ?? null,
        error: result.data ? null : describeSearchFailure(result.response?.status),
      });
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [key]);

  return { data: loaded?.data ?? null, error: loaded?.error ?? null, loading: loaded?.key !== key };
}

/**
 * Loads the filter checkbox values once. If they cannot be loaded the panel simply offers no
 * checkboxes; typed filters (titles, company names, revenue) still work.
 */
export function useFilterOptions(): FilterOptionsResponse | null {
  const [options, setOptions] = useState<FilterOptionsResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    void getFilterOptionsSearchFilterOptionsGet().then((result) => {
      if (!cancelled && result.data) setOptions(result.data);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return options;
}
