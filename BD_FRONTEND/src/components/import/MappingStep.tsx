"use client";

/**
 * Column-mapping step of the import wizard (task M2-A2 UI; D-040, D-049, D-069, Q-IMPORT-11).
 *
 * Needed so the uploader can see how each file column maps to a lead field, fix a missing or
 * wrong header by choosing a field for the column, ignore columns (they stay in the raw rows),
 * and save the mapping. Admins may also save it as a profile's default. Field lists, aliases and
 * the mandatory-field rule come from the server; the "used twice" hint is a courtesy and the
 * server's 422 is the source of truth. Showing the admin button is not access control.
 */
import { useEffect, useState } from "react";

import "@/lib/api-client";
import {
  listProfileOptionsImportsProfilesGet,
  listTargetFieldsImportsTargetFieldsGet,
  putMappingImportsImportIdMappingPut,
  readMappingImportsImportIdMappingGet,
  saveAsProfileDefaultImportsImportIdMappingSaveAsDefaultPost,
} from "@/lib/api/sdk.gen";
import type {
  MappingResponse,
  ProfileOptionResponse,
  TargetFieldResponse,
} from "@/lib/api/types.gen";
import { useCurrentUser } from "@/lib/auth-context";
import { errorMessage } from "@/lib/import/errors";
import {
  duplicateTargets,
  groupFields,
  selectionFromColumns,
  toEntries,
  type Selection,
} from "@/lib/import/mapping-form";
import { blockingIssueText, originText } from "@/lib/import/messages";

type Props = Readonly<{ importId: string; onDone: () => void }>;

const IGNORE_VALUE = "";
const NO_HEADER_LABEL = "(no header)";

/** Renders the mapping table with save, continue and the admin-only save-as-default. */
export default function MappingStep({ importId, onDone }: Props) {
  const user = useCurrentUser();
  const [mapping, setMapping] = useState<MappingResponse | null>(null);
  const [fields, setFields] = useState<TargetFieldResponse[]>([]);
  const [selection, setSelection] = useState<Selection>({});
  const [saved, setSaved] = useState<MappingResponse | null>(null);
  const [profiles, setProfiles] = useState<ProfileOptionResponse[]>([]);
  const [defaultProfileId, setDefaultProfileId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isAdmin = user.role === "admin";

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [current, targets, options] = await Promise.all([
        readMappingImportsImportIdMappingGet({ path: { import_id: importId } }),
        listTargetFieldsImportsTargetFieldsGet(),
        listProfileOptionsImportsProfilesGet(),
      ]);
      if (cancelled) return;
      if (current.data && targets.data) {
        setMapping(current.data);
        setFields(targets.data);
        setSelection(selectionFromColumns(current.data.columns));
        if (current.data.is_saved) setSaved(current.data);
      } else {
        const failed = current.data ? targets : current;
        setError(errorMessage(failed.error, failed.response));
      }
      if (options.data) {
        setProfiles(options.data);
        setDefaultProfileId(options.data[0]?.id ?? "");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [importId]);

  /** Changes one column's target; any edit invalidates the last save until saved again. */
  function choose(columnIndex: number, value: string) {
    setSelection((current) => ({ ...current, [columnIndex]: value === IGNORE_VALUE ? null : value }));
    setSaved(null);
    setNotice(null);
  }

  /** Sends the mapping; the server answers with what still blocks the import. */
  async function save() {
    setError(null);
    setNotice(null);
    setBusy(true);
    const result = await putMappingImportsImportIdMappingPut({
      path: { import_id: importId },
      body: { columns: toEntries(selection) },
    });
    setBusy(false);
    if (result.data) {
      setSaved(result.data);
      setMapping(result.data);
      return;
    }
    setError(errorMessage(result.error, result.response));
  }

  /** Admin only (the server enforces it): stores this mapping as the profile's defaults. */
  async function saveAsDefault() {
    setError(null);
    setNotice(null);
    setBusy(true);
    const result = await saveAsProfileDefaultImportsImportIdMappingSaveAsDefaultPost({
      path: { import_id: importId },
      body: { source_profile_id: defaultProfileId },
    });
    setBusy(false);
    if (result.data) {
      setNotice(`Saved as the profile default (${result.data.columns_in_defaults} columns).`);
      return;
    }
    setError(errorMessage(result.error, result.response));
  }

  if (!mapping) {
    return error ? <p role="alert">{error}</p> : <p>Loading the columns…</p>;
  }

  const repeated = duplicateTargets(selection);
  const groups = groupFields(fields);
  const issues = saved?.blocking_issues ?? [];
  const canContinue = saved !== null && issues.length === 0;

  return (
    <section aria-labelledby="mapping-title">
      <h2 id="mapping-title">Map the columns</h2>
      <p>
        Choose which lead field each column fills. Columns set to &quot;Ignore&quot; stay in the
        raw rows and are not lost.
      </p>
      <table>
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Column header</th>
            <th scope="col">Maps to</th>
            <th scope="col">Source of suggestion</th>
          </tr>
        </thead>
        <tbody>
          {mapping.columns.map((column) => {
            const label = column.source_header || NO_HEADER_LABEL;
            const current = selection[column.column_index];
            return (
              <tr key={column.column_index}>
                <td>{column.column_index + 1}</td>
                <td>{label}</td>
                <td>
                  <select
                    aria-label={`Field for column ${column.column_index + 1}: ${label}`}
                    value={current ?? IGNORE_VALUE}
                    onChange={(event) => choose(column.column_index, event.target.value)}
                  >
                    <option value={IGNORE_VALUE}>Ignore this column</option>
                    {groups.map(([group, groupFields]) => (
                      <optgroup key={group} label={group}>
                        {groupFields.map((field) => (
                          <option key={field.key} value={field.key}>
                            {field.label}
                            {field.required ? " (required)" : ""}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                  {current && repeated.has(current) && (
                    <span role="status"> Used by more than one column.</span>
                  )}
                  {!column.source_header && current === null && (
                    <span role="status"> No header: assign a field or ignore it.</span>
                  )}
                </td>
                <td>{originText(column.origin)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {issues.length > 0 && (
        <ul role="alert">
          {issues.map((code) => (
            <li key={code}>{blockingIssueText(code)}</li>
          ))}
        </ul>
      )}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}

      <button className="button" type="button" disabled={busy} onClick={() => void save()}>
        {busy ? "Saving…" : "Save mapping"}
      </button>{" "}
      <button className="button" type="button" disabled={busy || !canContinue} onClick={onDone}>
        Continue
      </button>

      {isAdmin && profiles.length > 0 && (
        <div>
          <label className="field">
            <span>Profile to update</span>
            <select
              value={defaultProfileId}
              onChange={(event) => setDefaultProfileId(event.target.value)}
            >
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button button-secondary"
            type="button"
            disabled={busy || saved === null}
            onClick={() => void saveAsDefault()}
          >
            Save as profile default
          </button>
        </div>
      )}
    </section>
  );
}
