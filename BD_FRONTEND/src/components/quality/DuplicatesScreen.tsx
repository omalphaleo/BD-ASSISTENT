"use client";

/**
 * The duplicate review screen (task M2-B5, milestone/m2.md section 19).
 *
 * Needed so a manager or admin can settle the pairs the import flagged as possible duplicates:
 * open a pair, compare the two people, merge them or say they are different (D-092, D-108).
 * Every action is a call to the generated API client and the screen shows what the server
 * answered. It decides nothing: the buttons are shown to every signed-in user and the server
 * allows or refuses each call (a refusal is shown as a message).
 */
import { useEffect, useState } from "react";

import DuplicateCompare from "@/components/quality/DuplicateCompare";
import {
  listDuplicatesDuplicatesGet,
  markNotDuplicateDuplicatesCandidateIdNotDuplicatePost,
  mergeDuplicateDuplicatesCandidateIdMergePost,
  type DuplicateCandidateResponse,
  type DuplicateListResponse,
  type DuplicateStatusFilter,
} from "@/lib/api-client";
import { describeReviewFailure, personSummary } from "@/lib/quality/review";

const PAGE_SIZE = 25;
const STATUS_OPTIONS: ReadonlyArray<{ value: DuplicateStatusFilter; label: string }> = [
  { value: "open", label: "Waiting for a decision" },
  { value: "not_duplicate", label: "Marked not a duplicate" },
];

type Notice = Readonly<{ kind: "success" | "error"; text: string }>;
type Loaded = Readonly<{ key: string; data: DuplicateListResponse | null; error: string | null }>;

/** Renders the filter, the list of pairs and the comparison of the pair being reviewed. */
export default function DuplicatesScreen() {
  const [status, setStatus] = useState<DuplicateStatusFilter>("open");
  const [offset, setOffset] = useState(0);
  const [reloadCount, setReloadCount] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [reviewingId, setReviewingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // A new key means "the list on screen is out of date": filter, page and reloads change it.
  const requestKey = `${status}|${offset}|${reloadCount}`;
  const loading = loaded?.key !== requestKey;

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const result = await listDuplicatesDuplicatesGet({
        query: { status, limit: PAGE_SIZE, offset },
      });
      if (cancelled) return; // a newer request replaced this one
      setLoaded({
        key: requestKey,
        data: result.data ?? null,
        error: result.data ? null : describeReviewFailure(result.response?.status, result.error),
      });
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [status, offset, requestKey]);

  const pairs = loaded?.data?.items ?? [];
  const total = loaded?.data?.total ?? 0;

  function reload() {
    setReloadCount((count) => count + 1);
  }

  function changeStatus(next: DuplicateStatusFilter) {
    setStatus(next);
    setOffset(0);
    setReviewingId(null);
  }

  /** Shows a failure and refreshes the list when the pair is gone or already decided. */
  function failWith(response: Response | undefined, error: unknown) {
    const code = response?.status;
    setNotice({ kind: "error", text: describeReviewFailure(code, error) });
    if (code === 404 || code === 409) {
      setReviewingId(null);
      reload();
    }
  }

  async function handleMerge(pair: DuplicateCandidateResponse, survivorId: string, values: Record<string, string>) {
    setBusy(true);
    setNotice(null);
    const result = await mergeDuplicateDuplicatesCandidateIdMergePost({
      path: { candidate_id: pair.id },
      body: { survivor_id: survivorId, values },
    });
    setBusy(false);
    if (!result.data) {
      failWith(result.response, result.error);
      return;
    }
    setReviewingId(null);
    setNotice({ kind: "success", text: "Merged. The two records are now one lead." });
    reload();
  }

  async function handleNotDuplicate(pair: DuplicateCandidateResponse) {
    setBusy(true);
    setNotice(null);
    const result = await markNotDuplicateDuplicatesCandidateIdNotDuplicatePost({
      path: { candidate_id: pair.id },
    });
    setBusy(false);
    if (!result.data) {
      failWith(result.response, result.error);
      return;
    }
    setReviewingId(null);
    setNotice({ kind: "success", text: "Marked as not a duplicate. This pair will not be shown again." });
    reload();
  }

  const firstShown = total === 0 ? 0 : offset + 1;
  const lastShown = Math.min(offset + PAGE_SIZE, total);

  return (
    <section>
      <h1>Duplicates</h1>
      <p>
        People the import could not match with certainty. Compare each pair, then merge it or mark it as
        not a duplicate. Until you decide, both records stay out of campaigns.
      </p>

      <div className="toolbar">
        <label className="field">
          <span>Show</span>
          <select value={status} onChange={(e) => changeStatus(e.target.value as DuplicateStatusFilter)}>
            {STATUS_OPTIONS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {notice && (
        <p className={`notice notice-${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>
          {notice.text}
        </p>
      )}
      {loaded?.error && (
        <p className="notice notice-error" role="alert">
          {loaded.error}
        </p>
      )}

      {loading && <p aria-live="polite">Loading…</p>}
      {!loading && loaded?.data && pairs.length === 0 && <p>No pairs match this filter.</p>}

      {pairs.length > 0 && (
        <ul className="duplicate-list">
          {pairs.map((pair) => {
            const isReviewing = reviewingId === pair.id;
            return (
              <li key={pair.id} className="duplicate-item">
                <div className="duplicate-summary">
                  <div>
                    <strong>A:</strong> {personSummary(pair.person_a)}
                    <br />
                    <strong>B:</strong> {personSummary(pair.person_b)}
                    <br />
                    <span className="muted">Reason: same name at the same company domain</span>
                  </div>
                  {pair.status === "open" && (
                    <button
                      className="button button-secondary"
                      type="button"
                      aria-label={`Review ${personSummary(pair.person_a)}`}
                      onClick={() => setReviewingId(isReviewing ? null : pair.id)}
                    >
                      {isReviewing ? "Hide" : "Review"}
                    </button>
                  )}
                </div>
                {isReviewing && (
                  <DuplicateCompare
                    pair={pair}
                    busy={busy}
                    onMerge={(survivorId, values) => void handleMerge(pair, survivorId, values)}
                    onNotDuplicate={() => void handleNotDuplicate(pair)}
                    onClose={() => setReviewingId(null)}
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}

      {total > 0 && (
        <nav className="pager" aria-label="Pages">
          <span>
            Showing {firstShown}–{lastShown} of {total}
          </span>
          <button
            className="button button-secondary"
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </button>
          <button
            className="button button-secondary"
            type="button"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </button>
        </nav>
      )}
    </section>
  );
}
