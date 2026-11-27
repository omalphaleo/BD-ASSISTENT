"use client";

/**
 * Detail panel of one source profile (task M2-A6 UI, D-049).
 *
 * Needed so an admin can rename a profile, change its layout label, activate or deactivate it
 * (a warning from the server is shown when imports in progress still use it, and deactivation is
 * never blocked), and forget saved header mappings. Profiles are never deleted. The server owns
 * every rule; this panel only calls the generated client and shows its fixed messages.
 */
import { useEffect, useState, type FormEvent } from "react";

import "@/lib/api-client";
import {
  editSourceProfileSourceProfilesProfileIdPatch,
  readSourceProfileSourceProfilesProfileIdGet,
  removeSourceProfileColumnsSourceProfilesProfileIdRemoveColumnsPost,
} from "@/lib/api/sdk.gen";
import type { SourceProfileDetailResponse } from "@/lib/api/types.gen";
import { errorMessage } from "@/lib/import/errors";

type Props = Readonly<{ profileId: string; onChanged: () => void; onClose: () => void }>;

/** Renders the edit form, the activate toggle, warnings and the saved header list. */
export default function SourceProfileDetail({ profileId, onChanged, onClose }: Props) {
  const [profile, setProfile] = useState<SourceProfileDetailResponse | null>(null);
  const [name, setName] = useState("");
  const [layout, setLayout] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /** Shows a saved profile in the form fields. */
  function show(next: SourceProfileDetailResponse) {
    setProfile(next);
    setName(next.name);
    setLayout(next.layout);
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const result = await readSourceProfileSourceProfilesProfileIdGet({
        path: { profile_id: profileId },
      });
      if (cancelled) return;
      if (result.data) show(result.data);
      else setError(errorMessage(result.error, result.response));
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [profileId]);

  /** Sends one edit; on success shows the updated profile and any warning the server returned. */
  async function save(body: { name?: string; layout?: string; is_active?: boolean }) {
    setError(null);
    setBusy(true);
    const result = await editSourceProfileSourceProfilesProfileIdPatch({
      path: { profile_id: profileId },
      body,
    });
    setBusy(false);
    if (!result.data) {
      setError(errorMessage(result.error, result.response));
      return;
    }
    show(result.data);
    setWarnings(result.data.warnings ?? []);
    onChanged();
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void save({ name: name.trim(), layout: layout.trim() });
  }

  /** Forgets one saved header mapping; the server returns the profile without it. */
  async function removeColumn(header: string) {
    setError(null);
    setBusy(true);
    const result = await removeSourceProfileColumnsSourceProfilesProfileIdRemoveColumnsPost({
      path: { profile_id: profileId },
      body: { headers: [header] },
    });
    setBusy(false);
    if (!result.data) {
      setError(errorMessage(result.error, result.response));
      return;
    }
    show(result.data);
    onChanged();
  }

  if (!profile) {
    return error ? <p role="alert">{error}</p> : <p>Loading…</p>;
  }

  const savedColumns = Object.entries(profile.columns);
  return (
    <section aria-label={`Profile ${profile.name}`}>
      <h2>{profile.name}</h2>
      {error && <p role="alert">{error}</p>}
      {warnings.map((warning) => (
        <p key={warning} role="status">
          {warning}
        </p>
      ))}
      <form onSubmit={handleSubmit}>
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label className="field">
          <span>Layout label</span>
          <input value={layout} onChange={(event) => setLayout(event.target.value)} />
        </label>
        <button className="button" type="submit" disabled={busy || !name.trim()}>
          Save changes
        </button>{" "}
        <button
          className="button button-secondary"
          type="button"
          disabled={busy}
          onClick={() => void save({ is_active: !profile.is_active })}
        >
          {profile.is_active ? "Deactivate" : "Activate"}
        </button>{" "}
        <button className="button button-secondary" type="button" onClick={onClose}>
          Close
        </button>
      </form>

      <h3>Saved column mapping</h3>
      {!profile.defaults_valid && <p>The saved mapping is no longer usable.</p>}
      {savedColumns.length === 0 ? (
        <p>No saved columns. Save a mapping from an import to add some.</p>
      ) : (
        <ul>
          {savedColumns.map(([header, field]) => (
            <li key={header}>
              {header} → {field}{" "}
              <button
                className="button button-secondary"
                type="button"
                disabled={busy}
                onClick={() => void removeColumn(header)}
              >
                Remove {header}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
