"use client";

/**
 * Data hook for the saved segments panel on the Leads search page (task M3-A4).
 *
 * Needed so the panel only says what the user wants (save, rename, share, delete) and gets back
 * the list, a busy flag and an error text. Calls the generated API client (the CSRF header is
 * added by `lib/api-client.ts`); holds no rule. After every write the list is reloaded from the
 * server, so what is on screen is what the server stores, including after a refused change.
 */
import { useCallback, useEffect, useState } from "react";

import {
  createSegmentSegmentsPost,
  deleteSegmentSegmentsSegmentIdDelete,
  listSegmentsSegmentsGet,
  updateSegmentSegmentsSegmentIdPatch,
} from "@/lib/api/sdk.gen";
import type { SegmentResponse, SegmentUpdate, SegmentVisibility } from "@/lib/api/types.gen";
import type { FilterSet } from "@/lib/search/filters";
import { describeSegmentFailure } from "@/lib/search/segments";

/** The panel's view of the segments: the list (null until the first answer) and what is going on. */
export type SegmentsState = Readonly<{
  segments: SegmentResponse[] | null;
  /** Failure text of the latest request, or null when it worked. */
  error: string | null;
  /** True while a write is in flight, so the panel can disable its buttons. */
  busy: boolean;
  /** Saves `filters` under `name`; resolves true when the server accepted it. */
  create: (name: string, filters: FilterSet, visibility: SegmentVisibility) => Promise<boolean>;
  /** Renames and/or shares a segment; resolves true when the server accepted it. */
  update: (id: string, change: SegmentUpdate) => Promise<boolean>;
  /** Deletes a segment; resolves true when the server accepted it. */
  remove: (id: string) => Promise<boolean>;
}>;

/** What every generated call returns that this hook reads: a status, and an ok flag. */
type Outcome = { response?: Response };

/** Loads the segments once, and gives the panel the functions that change them. */
export function useSegments(): SegmentsState {
  const [segments, setSegments] = useState<SegmentResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async (): Promise<boolean> => {
    try {
      const result = await listSegmentsSegmentsGet();
      if (result.data) {
        setSegments(result.data.items);
        return true;
      }
      setError(describeSegmentFailure(result.response?.status));
    } catch {
      setError(describeSegmentFailure(undefined)); // no answer at all: fixed message, no details
    }
    return false;
  }, []);

  useEffect(() => {
    let cancelled = false;
    void listSegmentsSegmentsGet().then((result) => {
      if (cancelled) return; // the screen was left before the answer came
      if (result.data) setSegments(result.data.items);
      else setError(describeSegmentFailure(result.response?.status));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  /**
   * Runs one write, then reloads the list. A refused write shows its message and still reloads,
   * so a segment that vanished or changed owner disappears from the screen straight away.
   */
  const write = useCallback(
    async (send: () => Promise<Outcome>): Promise<boolean> => {
      setBusy(true);
      setError(null);
      try {
        let accepted: boolean;
        try {
          const result = await send();
          accepted = result.response?.ok === true;
          if (!accepted) setError(describeSegmentFailure(result.response?.status));
        } catch {
          // The request never got an answer (network down): show the fixed message, no details.
          accepted = false;
          setError(describeSegmentFailure(undefined));
        }
        await reload();
        return accepted;
      } finally {
        setBusy(false);
      }
    },
    [reload],
  );

  const create = useCallback(
    (name: string, filters: FilterSet, visibility: SegmentVisibility) =>
      write(() => createSegmentSegmentsPost({ body: { name, filters, visibility } })),
    [write],
  );
  const update = useCallback(
    (id: string, change: SegmentUpdate) =>
      write(() =>
        updateSegmentSegmentsSegmentIdPatch({ path: { segment_id: id }, body: change }),
      ),
    [write],
  );
  const remove = useCallback(
    (id: string) =>
      write(() => deleteSegmentSegmentsSegmentIdDelete({ path: { segment_id: id } })),
    [write],
  );

  return { segments, error, busy, create, update, remove };
}
