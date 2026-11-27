"use client";

/**
 * Profile and default-country step of the import wizard (task M2-A2 UI, D-040, D-078).
 *
 * Needed so the uploader can pick the source profile (a source's saved layout) and the default
 * country before mapping. Profiles whose saved headers match the file are only suggested (the
 * user must click "Use this profile"); nothing is applied automatically. It calls the generated
 * client only; the server validates the profile and the country.
 */
import { useEffect, useState, type FormEvent } from "react";

import "@/lib/api-client";
import {
  listProfileOptionsImportsProfilesGet,
  readMappingImportsImportIdMappingGet,
  setImportProfileImportsImportIdProfilePut,
} from "@/lib/api/sdk.gen";
import type { ProfileOptionResponse, ProfileSuggestionResponse } from "@/lib/api/types.gen";
import { errorMessage } from "@/lib/import/errors";

type Props = Readonly<{ importId: string; onDone: () => void }>;

/** Renders the profile picker, the suggestions and the default-country field. */
export default function ProfileStep({ importId, onDone }: Props) {
  const [profiles, setProfiles] = useState<ProfileOptionResponse[]>([]);
  const [suggestions, setSuggestions] = useState<ProfileSuggestionResponse[]>([]);
  const [profileId, setProfileId] = useState("");
  const [country, setCountry] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Load the choices once: all usable profiles, and the profiles that match this file's headers.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [options, mapping] = await Promise.all([
        listProfileOptionsImportsProfilesGet(),
        readMappingImportsImportIdMappingGet({ path: { import_id: importId } }),
      ]);
      if (cancelled) return;
      if (options.data) setProfiles(options.data);
      if (mapping.data) setSuggestions(mapping.data.profile_suggestions);
      if (!options.data) setError(errorMessage(options.error, options.response));
      else if (!mapping.data) setError(errorMessage(mapping.error, mapping.response));
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [importId]);

  /** Saves the choice (no profile is allowed) and moves on to the mapping step. */
  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    const result = await setImportProfileImportsImportIdProfilePut({
      path: { import_id: importId },
      body: {
        source_profile_id: profileId || null,
        default_country: country.trim() || null,
      },
    });
    setBusy(false);
    if (result.data) {
      onDone();
      return;
    }
    setError(errorMessage(result.error, result.response));
  }

  return (
    <form onSubmit={(event) => void handleSubmit(event)}>
      <h2>Source profile and country</h2>
      {suggestions.length > 0 && (
        <div>
          <p>This file looks like a saved source. Use it only if it is right:</p>
          <ul>
            {suggestions.map((suggestion) => (
              <li key={suggestion.source_profile_id}>
                {suggestion.name} ({Math.round(suggestion.overlap * 100)}% of its columns match){" "}
                <button
                  className="button button-secondary"
                  type="button"
                  onClick={() => setProfileId(suggestion.source_profile_id)}
                >
                  Use this profile
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <label className="field">
        <span>Source profile</span>
        <select value={profileId} onChange={(event) => setProfileId(event.target.value)}>
          <option value="">No profile (built-in column names)</option>
          {profiles.map((profile) => (
            <option key={profile.id} value={profile.id}>
              {profile.name}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Default country (optional)</span>
        <input value={country} onChange={(event) => setCountry(event.target.value)} />
      </label>
      {error && <p role="alert">{error}</p>}
      <button className="button" type="submit" disabled={busy}>
        {busy ? "Saving…" : "Continue"}
      </button>
    </form>
  );
}
