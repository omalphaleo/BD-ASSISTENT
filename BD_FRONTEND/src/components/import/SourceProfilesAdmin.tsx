"use client";

/**
 * Source profile admin: list and create (task M2-A6 UI, D-049, D-104).
 *
 * Needed so an admin can see every saved source profile (a source's column layout and saved
 * mapping), add one, and open one to edit it. The server enforces MANAGE_SOURCE_PROFILES and the
 * unique-name rule; this component only calls the generated client and shows the server's fixed
 * messages. Editing one profile is in SourceProfileDetail.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";

import "@/lib/api-client";
import {
  createSourceProfileSourceProfilesPost,
  listSourceProfilesSourceProfilesGet,
} from "@/lib/api/sdk.gen";
import type { SourceProfileResponse } from "@/lib/api/types.gen";
import { errorMessage } from "@/lib/import/errors";

import SourceProfileDetail from "./SourceProfileDetail";

/** Renders the profile table, the create form and the detail panel of the selected profile. */
export default function SourceProfilesAdmin() {
  const [profiles, setProfiles] = useState<SourceProfileResponse[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [layout, setLayout] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Bumping this counter reloads the list: on mount and after any change in the detail panel.
  const [reloadKey, setReloadKey] = useState(0);
  const reload = useCallback(() => setReloadKey((key) => key + 1), []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const result = await listSourceProfilesSourceProfilesGet();
      if (cancelled) return;
      if (result.data) {
        setProfiles(result.data);
        setError(null);
      } else {
        setError(errorMessage(result.error, result.response));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  /** Creates an active profile with no saved mapping, then opens it. */
  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    const result = await createSourceProfileSourceProfilesPost({
      body: { name: name.trim(), layout: layout.trim() },
    });
    setBusy(false);
    if (!result.data) {
      setError(errorMessage(result.error, result.response));
      return;
    }
    setName("");
    setLayout("");
    setSelectedId(result.data.id);
    reload();
  }

  return (
    <div>
      {error && <p role="alert">{error}</p>}
      <form onSubmit={(event) => void handleCreate(event)}>
        <h2>New source profile</h2>
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label className="field">
          <span>Layout label</span>
          <input value={layout} onChange={(event) => setLayout(event.target.value)} />
        </label>
        <button className="button" type="submit" disabled={busy || !name.trim()}>
          {busy ? "Creating…" : "Create profile"}
        </button>
      </form>

      <h2>Profiles</h2>
      {profiles === null ? (
        <p>Loading…</p>
      ) : profiles.length === 0 ? (
        <p>No source profiles yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Layout</th>
              <th>Status</th>
              <th>Saved columns</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {profiles.map((profile) => (
              <tr key={profile.id}>
                <td>{profile.name}</td>
                <td>{profile.layout}</td>
                <td>{profile.is_active ? "Active" : "Inactive"}</td>
                <td>
                  {profile.saved_column_count}
                  {!profile.defaults_valid && " (saved mapping unusable)"}
                </td>
                <td>
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => setSelectedId(profile.id)}
                  >
                    Open
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selectedId && (
        <SourceProfileDetail
          key={selectedId}
          profileId={selectedId}
          onChanged={reload}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}
