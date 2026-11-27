"use client";

/**
 * The industry mapping list, add form and inline editor (task M2-B6, D-076).
 *
 * Needed so an admin can teach the app a new industry wording ("Software Dev" means
 * "Information") that later imports then use. The screen only lists, adds and edits through the
 * generated client and shows the server's answer; it checks no role (the server allows or
 * refuses) and no rule (the server trims, lowercases and rejects repeats).
 */
import { useEffect, useState, type FormEvent } from "react";

import {
  createIndustryMappingReferenceMappingsIndustriesPost,
  listIndustryMappingsReferenceMappingsIndustriesGet,
  updateIndustryMappingReferenceMappingsIndustriesMappingIdPatch,
  type IndustryMappingListResponse,
  type IndustryMappingResponse,
} from "@/lib/api-client";
import { describeReviewFailure } from "@/lib/quality/review";

const PAGE_SIZE = 25;

type Notice = Readonly<{ kind: "success" | "error"; text: string }>;
type Loaded = Readonly<{ key: string; data: IndustryMappingListResponse | null; error: string | null }>;
type Draft = { source_name: string; standard_industry: string; naics_sector: string };

const EMPTY_DRAFT: Draft = { source_name: "", standard_industry: "", naics_sector: "" };

/** Turns a form text into the value sent: blank sector text means "no sector". */
function sectorOrNull(text: string): string | null {
  return text.trim() === "" ? null : text.trim();
}

/** Renders search, the table of industry mappings, the add form and the inline editor. */
export default function IndustryMappingsPanel() {
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
      const result = await listIndustryMappingsReferenceMappingsIndustriesGet({
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
    const result = await createIndustryMappingReferenceMappingsIndustriesPost({
      body: {
        source_name: newDraft.source_name,
        standard_industry: newDraft.standard_industry,
        naics_sector: sectorOrNull(newDraft.naics_sector),
      },
    });
    setBusy(false);
    if (!result.data) {
      setNotice({ kind: "error", text: describeReviewFailure(result.response?.status, result.error) });
      return;
    }
    setNewDraft(EMPTY_DRAFT);
    setNotice({ kind: "success", text: "Industry mapping added." });
    setReloadCount((count) => count + 1);
  }

  function startEdit(row: IndustryMappingResponse) {
    setEditingId(row.id);
    setEditDraft({
      source_name: row.source_name,
      standard_industry: row.standard_industry,
      naics_sector: row.naics_sector ?? "",
    });
  }

  async function handleSave(row: IndustryMappingResponse) {
    setBusy(true);
    setNotice(null);
    const result = await updateIndustryMappingReferenceMappingsIndustriesMappingIdPatch({
      path: { mapping_id: row.id },
      body: {
        source_name: editDraft.source_name,
        standard_industry: editDraft.standard_industry,
        naics_sector: sectorOrNull(editDraft.naics_sector),
      },
    });
    setBusy(false);
    if (!result.data) {
      setNotice({ kind: "error", text: describeReviewFailure(result.response?.status, result.error) });
      if (result.response?.status === 404) setReloadCount((count) => count + 1);
      return;
    }
    setEditingId(null);
    setNotice({ kind: "success", text: "Industry mapping saved." });
    setReloadCount((count) => count + 1);
  }

  return (
    <div>
      <p>
        Each line says that a wording found in an import file means a standard industry. Imports use
        these lines automatically.
      </p>

      <form className="toolbar" onSubmit={applySearch} aria-label="Search industry mappings">
        <label className="field">
          <span>Search wording</span>
          <input type="text" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <button className="button button-secondary" type="submit">
          Search
        </button>
      </form>

      <form className="toolbar" onSubmit={(e) => void handleAdd(e)} aria-label="Add industry mapping">
        <label className="field">
          <span>Wording in the file</span>
          <input
            type="text"
            value={newDraft.source_name}
            onChange={(e) => setNewDraft({ ...newDraft, source_name: e.target.value })}
          />
        </label>
        <label className="field">
          <span>Standard industry</span>
          <input
            type="text"
            value={newDraft.standard_industry}
            onChange={(e) => setNewDraft({ ...newDraft, standard_industry: e.target.value })}
          />
        </label>
        <label className="field">
          <span>NAICS sector (optional)</span>
          <input
            type="text"
            value={newDraft.naics_sector}
            onChange={(e) => setNewDraft({ ...newDraft, naics_sector: e.target.value })}
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
      {!loading && loaded?.data && rows.length === 0 && <p>No industry mappings match.</p>}

      {rows.length > 0 && (
        <table className="data-table">
          <caption className="visually-hidden">Industry mappings</caption>
          <thead>
            <tr>
              <th scope="col">Wording in the file</th>
              <th scope="col">Standard industry</th>
              <th scope="col">NAICS sector</th>
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
                      aria-label="Wording in the file"
                      value={editDraft.source_name}
                      onChange={(e) => setEditDraft({ ...editDraft, source_name: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      type="text"
                      aria-label="Standard industry"
                      value={editDraft.standard_industry}
                      onChange={(e) => setEditDraft({ ...editDraft, standard_industry: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      type="text"
                      aria-label="NAICS sector"
                      value={editDraft.naics_sector}
                      onChange={(e) => setEditDraft({ ...editDraft, naics_sector: e.target.value })}
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
                  <td>{row.source_name}</td>
                  <td>{row.standard_industry}</td>
                  <td>{row.naics_sector ?? "—"}</td>
                  <td>
                    <button
                      className="button button-secondary"
                      type="button"
                      aria-label={`Edit ${row.source_name}`}
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
        <nav className="pager" aria-label="Industry pages">
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
