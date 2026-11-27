"use client";

/**
 * The saved segments panel on the Leads search page (task M3-A4, D-009, D-098).
 *
 * Needed so BD can save the filters they are using under a name, reuse them later with one click
 * and share them with the team. Segments are private to their owner unless shared; only the owner
 * sees Rename, Share and Delete, but the server decides and re-checks every change. Applying a
 * segment hands its filters to the screen, which runs the search like any other Apply. A segment
 * whose saved filters are no longer supported is listed with Apply switched off. Names are shown
 * as plain text and never as HTML.
 */
import { useState } from "react";

import styles from "@/components/search/search.module.css";
import type { SegmentResponse } from "@/lib/api/types.gen";
import type { FilterSet } from "@/lib/search/filters";
import {
  MAX_SEGMENT_NAME_LENGTH,
  groupSegments,
  isSaveableName,
  ownerLabel,
} from "@/lib/search/segments";
import { useSegments } from "@/lib/search/use-segments";

/** One row: the name, who shared it, and the actions the caller may use. */
function SegmentRow({
  segment,
  busy,
  onApply,
  onRename,
  onToggleShare,
  onDelete,
}: Readonly<{
  segment: SegmentResponse;
  busy: boolean;
  onApply: (filters: FilterSet) => void;
  onRename: (id: string, name: string) => Promise<boolean>;
  onToggleShare: (segment: SegmentResponse) => void;
  onDelete: (id: string) => Promise<boolean>;
}>) {
  const [renaming, setRenaming] = useState(false);
  const [draftName, setDraftName] = useState(segment.name);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const isShared = segment.visibility === "shared";

  async function saveRename() {
    if (await onRename(segment.id, draftName)) setRenaming(false);
  }

  return (
    <li className={styles.fieldLabel} style={{ gap: 6, marginBottom: 10 }}>
      {renaming ? (
        <span className={styles.termRow}>
          <input
            type="text"
            className={styles.input}
            aria-label={`New name for ${segment.name}`}
            maxLength={MAX_SEGMENT_NAME_LENGTH}
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
          />
          <button
            type="button"
            className={styles.secondary}
            disabled={busy || !isSaveableName(draftName)}
            onClick={() => void saveRename()}
          >
            Save name
          </button>
          <button type="button" className={styles.secondary} onClick={() => setRenaming(false)}>
            Cancel
          </button>
        </span>
      ) : (
        <span>
          <strong>{segment.name}</strong>{" "}
          <span className={styles.hint}>
            {isShared ? "Shared with the team" : "Private"}
            {!segment.can_edit && ` · ${ownerLabel(segment)}`}
          </span>
        </span>
      )}

      {!segment.filters_valid && (
        <p className={styles.error} role="status">
          This segment uses filters that are no longer supported, so it cannot be applied.
        </p>
      )}

      <span className={styles.chipRow}>
        <button
          type="button"
          className={styles.secondary}
          disabled={!segment.filters_valid || busy}
          onClick={() => segment.filters && onApply(segment.filters)}
          aria-label={`Apply segment ${segment.name}`}
        >
          Apply
        </button>
        {segment.can_edit && !renaming && !confirmingDelete && (
          <>
            <button
              type="button"
              className={styles.secondary}
              disabled={busy}
              onClick={() => {
                setDraftName(segment.name);
                setRenaming(true);
              }}
              aria-label={`Rename segment ${segment.name}`}
            >
              Rename
            </button>
            <button
              type="button"
              className={styles.secondary}
              disabled={busy}
              onClick={() => onToggleShare(segment)}
              aria-label={`${isShared ? "Make private" : "Share with the team"}: ${segment.name}`}
            >
              {isShared ? "Make private" : "Share with the team"}
            </button>
            <button
              type="button"
              className={styles.secondary}
              disabled={busy}
              onClick={() => setConfirmingDelete(true)}
              aria-label={`Delete segment ${segment.name}`}
            >
              Delete
            </button>
          </>
        )}
        {segment.can_edit && confirmingDelete && (
          <>
            <span className={styles.hint}>Delete this segment?</span>
            <button
              type="button"
              className={styles.secondary}
              disabled={busy}
              onClick={() => void onDelete(segment.id)}
              aria-label={`Confirm delete of ${segment.name}`}
            >
              Yes, delete
            </button>
            <button type="button" className={styles.secondary} onClick={() => setConfirmingDelete(false)}>
              Keep
            </button>
          </>
        )}
      </span>
    </li>
  );
}

/** Renders the save form and the two segment lists. `filters` is what the screen has applied. */
export default function SegmentPanel({
  filters,
  onApply,
}: Readonly<{ filters: FilterSet; onApply: (filters: FilterSet) => void }>) {
  const { segments, error, busy, create, update, remove } = useSegments();
  const [name, setName] = useState("");
  const [share, setShare] = useState(false);

  async function save() {
    const saved = await create(name.trim(), filters, share ? "shared" : "private");
    if (saved) {
      setName("");
      setShare(false);
    }
  }

  const groups = groupSegments(segments ?? []);

  return (
    <section className={styles.panel} aria-label="Saved segments">
      <div className={styles.panelHead}>
        <strong>Saved segments</strong>
      </div>
      <div className={styles.panelBody}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (isSaveableName(name)) void save();
          }}
        >
          <label className={styles.fieldLabel}>
            <span>Segment name</span>
            <span className={styles.termRow}>
              <input
                type="text"
                className={styles.input}
                maxLength={MAX_SEGMENT_NAME_LENGTH}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <button
                type="submit"
                className={styles.secondary}
                disabled={busy || !isSaveableName(name)}
              >
                Save current filters
              </button>
            </span>
          </label>
          <label className={styles.option}>
            <input type="checkbox" checked={share} onChange={(e) => setShare(e.target.checked)} />
            <span>Share with the team</span>
          </label>
          <p className={styles.hint}>Segments are private unless you share them.</p>
        </form>

        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
        {segments === null && !error && <p className={styles.hint}>Loading segments…</p>}
        {segments !== null && segments.length === 0 && (
          <p className={styles.hint}>No saved segments yet.</p>
        )}

        {[
          { title: "Your segments", items: groups.editable },
          { title: "Shared by colleagues", items: groups.sharedByOthers },
        ].map(
          ({ title, items }) =>
            items.length > 0 && (
              <div key={title}>
                <h3>{title}</h3>
                <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                  {items.map((segment) => (
                    <SegmentRow
                      key={segment.id}
                      segment={segment}
                      busy={busy}
                      onApply={onApply}
                      onRename={(id, next) => update(id, { name: next.trim() })}
                      onToggleShare={(s) =>
                        void update(s.id, {
                          visibility: s.visibility === "shared" ? "private" : "shared",
                        })
                      }
                      onDelete={remove}
                    />
                  ))}
                </ul>
              </div>
            ),
        )}
      </div>
    </section>
  );
}
