"use client";

/**
 * The quarantine review screen (task M2-B2, milestone/m2.md section 19).
 *
 * Needed so BD can see the import rows that failed validation, filter them, correct them,
 * release them into the lead database or discard them, instead of losing them (D-068, D-107).
 * Every action is a call to the generated API client and the screen shows what the server
 * answered. It decides nothing: all buttons are shown to every signed-in user, and the server
 * allows or refuses each call (a refusal is shown as a message). The one answer worth knowing
 * is 503 on release: the row is valid but the import step is not built yet (M2-B4), so the
 * screen says so and leaves the row where it is.
 */
import { Fragment, useEffect, useState } from "react";

import QuarantineEditor from "@/components/quality/QuarantineEditor";
import {
  discardQuarantineRecordQuarantineRecordIdDiscardPost,
  fixQuarantineRecordQuarantineRecordIdPatch,
  listQuarantineQuarantineGet,
  releaseQuarantineRecordQuarantineRecordIdReleasePost,
  type QuarantineListResponse,
  type QuarantineRecordResponse,
  type QuarantineStatusFilter,
  type RowIssue,
} from "@/lib/api-client";
import {
  ISSUE_OPTIONS,
  STATUS_OPTIONS,
  describeFailure,
  describeReleaseResult,
  displayValue,
  issueLabel,
  type QuarantineAction,
} from "@/lib/quality/quarantine";

const PAGE_SIZE = 25;

type Notice = Readonly<{ kind: "success" | "info" | "error"; text: string }>;
type Loaded = Readonly<{ key: string; data: QuarantineListResponse | null; error: string | null }>;

/** Formats the creation time for the list; the exact instant is not needed on screen. */
function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString();
}

/** Renders the filters, the list of quarantined rows and the row actions. */
export default function QuarantineScreen() {
  const [status, setStatus] = useState<QuarantineStatusFilter>("open");
  const [issue, setIssue] = useState<RowIssue | "">("");
  const [offset, setOffset] = useState(0);
  const [reloadCount, setReloadCount] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmingDiscardId, setConfirmingDiscardId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // A new key means "the list on screen is out of date": filters, page and reloads all change it.
  const requestKey = `${status}|${issue}|${offset}|${reloadCount}`;
  const loading = loaded?.key !== requestKey;

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const result = await listQuarantineQuarantineGet({
        query: { status, issue: issue === "" ? undefined : issue, limit: PAGE_SIZE, offset },
      });
      if (cancelled) return; // a newer request replaced this one
      setLoaded({
        key: requestKey,
        data: result.data ?? null,
        error: result.data ? null : describeFailure("load", result.response?.status, result.error),
      });
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [status, issue, offset, requestKey]);

  const records = loaded?.data?.items ?? [];
  const total = loaded?.data?.total ?? 0;

  function reload() {
    setReloadCount((count) => count + 1);
  }

  function changeStatus(next: QuarantineStatusFilter) {
    setStatus(next);
    setOffset(0);
    setEditingId(null);
  }

  function changeIssue(next: RowIssue | "") {
    setIssue(next);
    setOffset(0);
    setEditingId(null);
  }

  /** Shows a failure and refreshes the list when the record is gone or already resolved. */
  function failWith(action: QuarantineAction, response: Response | undefined, error: unknown) {
    const code = response?.status;
    setNotice({ kind: "error", text: describeFailure(action, code, error) });
    if (code === 404 || code === 409) reload();
  }

  async function handleSave(record: QuarantineRecordResponse, changes: Record<string, string>) {
    setBusyId(record.id);
    setNotice(null);
    const result = await fixQuarantineRecordQuarantineRecordIdPatch({
      path: { record_id: record.id },
      body: { values: changes },
    });
    setBusyId(null);
    if (!result.data) {
      failWith("save", result.response, result.error);
      return;
    }
    setEditingId(null);
    const remaining = result.data.issues;
    setNotice({
      kind: "success",
      text:
        remaining.length === 0
          ? "Saved. The row passes validation and is ready to release."
          : `Saved. Still to fix: ${remaining.map(issueLabel).join("; ")}.`,
    });
    reload();
  }

  async function handleRelease(record: QuarantineRecordResponse) {
    setBusyId(record.id);
    setNotice(null);
    const result = await releaseQuarantineRecordQuarantineRecordIdReleasePost({
      path: { record_id: record.id },
    });
    setBusyId(null);
    if (!result.data) {
      failWith("release", result.response, result.error);
      return;
    }
    setNotice({
      kind: result.data.released ? "success" : "info",
      text: describeReleaseResult(result.data.released, result.data.record.issues),
    });
    reload();
  }

  async function handleDiscard(record: QuarantineRecordResponse) {
    setBusyId(record.id);
    setNotice(null);
    setConfirmingDiscardId(null);
    const result = await discardQuarantineRecordQuarantineRecordIdDiscardPost({
      path: { record_id: record.id },
    });
    setBusyId(null);
    if (!result.data) {
      failWith("discard", result.response, result.error);
      return;
    }
    setNotice({ kind: "success", text: "Row discarded." });
    reload();
  }

  const firstShown = total === 0 ? 0 : offset + 1;
  const lastShown = Math.min(offset + PAGE_SIZE, total);

  return (
    <section>
      <h1>Quarantine</h1>
      <p>
        Rows from imports that need a fix before they can become leads. Correct a row, then release
        it, or discard it.
      </p>

      <div className="toolbar">
        <label className="field">
          <span>Status</span>
          <select value={status} onChange={(e) => changeStatus(e.target.value as QuarantineStatusFilter)}>
            {STATUS_OPTIONS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Reason</span>
          <select value={issue} onChange={(e) => changeIssue(e.target.value as RowIssue | "")}>
            {ISSUE_OPTIONS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {notice && (
        <p
          className={`notice notice-${notice.kind}`}
          role={notice.kind === "error" ? "alert" : "status"}
        >
          {notice.text}
        </p>
      )}
      {loaded?.error && (
        <p className="notice notice-error" role="alert">
          {loaded.error}
        </p>
      )}

      {loading && <p aria-live="polite">Loading…</p>}
      {!loading && loaded?.data && records.length === 0 && <p>No rows match these filters.</p>}

      {records.length > 0 && (
        <table className="data-table">
          <caption className="visually-hidden">Quarantined import rows</caption>
          <thead>
            <tr>
              <th scope="col">Source</th>
              <th scope="col">Person</th>
              <th scope="col">Reasons</th>
              <th scope="col">Status</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {records.map((record) => {
              const isOpen = record.status === "open";
              const busy = busyId === record.id;
              const label = `row ${record.row_number ?? "?"} of ${record.filename ?? "unknown file"}`;
              return (
                <Fragment key={record.id}>
                  <tr>
                    <td>
                      {record.filename ?? "Unknown file"}
                      <br />
                      <span className="muted">
                        Row {record.row_number ?? "?"} · {formatDate(record.created_at)}
                      </span>
                    </td>
                    <td>
                      {displayValue(record.payload.first_name) || "—"}
                      <br />
                      <span className="muted">{displayValue(record.payload.email) || "No email"}</span>
                    </td>
                    <td>
                      {record.issues.length === 0 ? (
                        <span className="badge badge-ok">Ready to release</span>
                      ) : (
                        record.issues.map((code) => (
                          <span className="badge" key={code}>
                            {issueLabel(code)}
                          </span>
                        ))
                      )}
                    </td>
                    <td>{record.status}</td>
                    <td>
                      {isOpen ? (
                        <div className="row-actions">
                          <button
                            className="button button-secondary"
                            type="button"
                            aria-label={`Edit ${label}`}
                            disabled={busy}
                            onClick={() => setEditingId(editingId === record.id ? null : record.id)}
                          >
                            Edit
                          </button>
                          <button
                            className="button"
                            type="button"
                            aria-label={`Release ${label}`}
                            disabled={busy}
                            onClick={() => void handleRelease(record)}
                          >
                            Release
                          </button>
                          {confirmingDiscardId === record.id ? (
                            <>
                              <button
                                className="button button-danger"
                                type="button"
                                aria-label={`Confirm discard ${label}`}
                                disabled={busy}
                                onClick={() => void handleDiscard(record)}
                              >
                                Confirm discard
                              </button>
                              <button
                                className="button button-secondary"
                                type="button"
                                onClick={() => setConfirmingDiscardId(null)}
                              >
                                Keep
                              </button>
                            </>
                          ) : (
                            <button
                              className="button button-secondary"
                              type="button"
                              aria-label={`Discard ${label}`}
                              disabled={busy}
                              onClick={() => setConfirmingDiscardId(record.id)}
                            >
                              Discard
                            </button>
                          )}
                        </div>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                  {isOpen && editingId === record.id && (
                    <tr>
                      <td colSpan={5}>
                        <QuarantineEditor
                          record={record}
                          saving={busy}
                          onSave={(changes) => void handleSave(record, changes)}
                          onCancel={() => setEditingId(null)}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
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
