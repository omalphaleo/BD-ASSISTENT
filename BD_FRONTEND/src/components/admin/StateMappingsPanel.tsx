"use client";

/**
 * The state mapping list, add form and inline editor (task M2-B6, D-078).
 *
 * Needed so an admin can teach the app a new state wording ("calif." means "California" for the
 * United States) that later imports then use. Like the industry panel it only lists, adds and
 * edits through the generated client and shows the server's answer; it checks no role and no
 * rule (the server trims, lowercases and rejects repeats per country).
 */
import { useEffect, useState, type FormEvent } from "react";

import {
  createStateMappingReferenceMappingsStatesPost,
  listStateMappingsReferenceMappingsStatesGet,
  updateStateMappingReferenceMappingsStatesMappingIdPatch,
  type StateMappingListResponse,
  type StateMappingResponse,
} from "@/lib/api-client";
import { describeReviewFailure } from "@/lib/quality/review";

const PAGE_SIZE = 25;

type Notice = Readonly<{ kind: "success" | "error"; text: string }>;
type Loaded = Readonly<{ key: string; data: StateMappingListResponse | null; error: string | null }>;
type Draft = { country: string; source_value: string; standard_name: string; abbreviation: string };

const EMPTY_DRAFT: Draft = { country: "United States", source_value: "", standard_name: "", abbreviation: "" };

/** Turns a form text into the value sent: blank abbreviation text means "no abbreviation". */
function abbreviationOrNull(text: string): string | null {
  return text.trim() === "" ? null : text.trim();
}

/** Renders search, the table of state mappings, the add form and the inline editor. */
export default function StateMappingsPanel() {
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [reloadCount, setReloadCount] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [newDraft, setNewDraft] = useState<Draft>(EMPTY_DRAFT);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<Draft>(EMPTY_DRAFT);
  const [busy, setBusy] = useState(false);

  const requestKey = `${appliedSearch}|${offset}|${reloadCount}`;
  const loading = loaded?.key !== requestKey;

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const result = await listStateMappingsReferenceMappingsStatesGet({
        query: { search: appliedSearch || undefined, limit: PAGE_SIZE, offset },
      });
      if (cancelled) return;
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
  }, [appliedSearch, offset, requestKey]);

  const rows = loaded?.data?.items ?? [];
  const total = loaded?.data?.total ?? 0;

  function applySearch(event: FormEvent) {
    event.preventDefault();
    setAppliedSearch(search.trim());
    setOffset(0);
  }

  async function handleAdd(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setNotice(null);
    const result = await createStateMappingReferenceMappingsStatesPost({
      body: {
        country: newDraft.country,
        source_value: newDraft.source_value,
        standard_name: newDraft.standard_name,
        abbreviation: abbreviationOrNull(newDraft.abbreviation),
      },
    });
    setBusy(false);
    if (!result.data) {
      setNotice({ kind: "error", text: describeReviewFailure(result.response?.status, result.error) });
      return;
    }
    setNewDraft(EMPTY_DRAFT);
    setNotice({ kind: "success", text: "State mapping added." });
    setReloadCount((count) => count + 1);
  }

  function startEdit(row: StateMappingResponse) {
    setEditingId(row.id);
    setEditDraft({
      country: row.country,
      source_value: row.source_value,
      standard_name: row.standard_name,
      abbreviation: row.abbreviation ?? "",
    });
  }

  async function handleSave(row: StateMappingResponse) {
    setBusy(true);
    setNotice(null);
    const result = await updateStateMappingReferenceMappingsStatesMappingIdPatch({
      path: { mapping_id: row.id },
      body: {
        country: editDraft.country,
        source_value: editDraft.source_value,
        standard_name: editDraft.standard_name,
        abbreviation: abbreviationOrNull(editDraft.abbreviation),
      },
    });
    setBusy(false);
    if (!result.data) {
      setNotice({ kind: "error", text: describeReviewFailure(result.response?.status, result.error) });
      if (result.response?.status === 404) setReloadCount((count) => count + 1);
      return;
    }
    setEditingId(null);
    setNotice({ kind: "success", text: "State mapping saved." });
    setReloadCount((count) => count + 1);
  }

  return (
    <div>
      <p>
        Each line says that a state wording found in an import file means a standard state name for a
        country. Imports use these lines automatically.
      </p>

      <form className="toolbar" onSubmit={applySearch} aria-label="Search state mappings">
        <label className="field">
          <span>Search wording</span>
          <input type="text" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <button className="button button-secondary" type="submit">
          Search
        </button>
      </form>

      <form className="toolbar" onSubmit={(e) => void handleAdd(e)} aria-label="Add state mapping">
        <label className="field">
          <span>Country</span>
          <input
            type="text"
            value={newDraft.country}
            onChange={(e) => setNewDraft({ ...newDraft, country: e.target.value })}
          />
        </label>
        <label className="field">
          <span>Wording in the file</span>
          <input
            type="text"
            value={newDraft.source_value}
            onChange={(e) => setNewDraft({ ...newDraft, source_value: e.target.value })}
          />
        </label>
        <label className="field">
          <span>Standard name</span>
          <input
            type="text"
            value={newDraft.standard_name}
            onChange={(e) => setNewDraft({ ...newDraft, standard_name: e.target.value })}
          />
        </label>
        <label className="field">
          <span>Abbreviation (optional)</span>
          <input
            type="text"
            value={newDraft.abbreviation}
            onChange={(e) => setNewDraft({ ...newDraft, abbreviation: e.target.value })}
          />
        </label>
        <button className="button" type="submit" disabled={busy}>
          Add mapping
        </button>
      </form>

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
      {!loading && loaded?.data && rows.length === 0 && <p>No state mappings match.</p>}

      {rows.length > 0 && (
        <table className="data-table">
          <caption className="visually-hidden">State mappings</caption>
          <thead>
            <tr>
              <th scope="col">Country</th>
              <th scope="col">Wording in the file</th>
              <th scope="col">Standard name</th>
              <th scope="col">Abbreviation</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) =>
              editingId === row.id ? (
                <tr key={row.id}>
                  <td>
                    <input
                      type="text"
                      aria-label="Country"
                      value={editDraft.country}
                      onChange={(e) => setEditDraft({ ...editDraft, country: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      type="text"
                      aria-label="Wording in the file"
                      value={editDraft.source_value}
                      onChange={(e) => setEditDraft({ ...editDraft, source_value: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      type="text"
                      aria-label="Standard name"
                      value={editDraft.standard_name}
                      onChange={(e) => setEditDraft({ ...editDraft, standard_name: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      type="text"
                      aria-label="Abbreviation"
                      value={editDraft.abbreviation}
                      onChange={(e) => setEditDraft({ ...editDraft, abbreviation: e.target.value })}
                    />
                  </td>
                  <td>
                    <div className="row-actions">
                      <button className="button" type="button" disabled={busy} onClick={() => void handleSave(row)}>
                        Save
                      </button>
                      <button className="button button-secondary" type="button" onClick={() => setEditingId(null)}>
                        Cancel
                      </button>
                    </div>
                  </td>
                </tr>
              ) : (
                <tr key={row.id}>
                  <td>{row.country}</td>
                  <td>{row.source_value}</td>
                  <td>{row.standard_name}</td>
                  <td>{row.abbreviation ?? "—"}</td>
                  <td>
                    <button
                      className="button button-secondary"
                      type="button"
                      aria-label={`Edit ${row.source_value}`}
                      onClick={() => startEdit(row)}
                    >
                      Edit
                    </button>
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      )}

      {total > 0 && (
        <nav className="pager" aria-label="State pages">
          <span>
            Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
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
    </div>
  );
}
