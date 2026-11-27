"use client";

/**
 * Progress and result view of a running or finished import (task M2-A4 UI; D-050, D-075).
 *
 * Needed so the uploader sees how far a large import is instead of a frozen page. It asks the
 * server for the counters every few seconds until the import is finished and shows them as the
 * server reports them (nothing is calculated here). When the import has completed, managers and
 * admins also get the panel to assign leads whose source owner matched no user.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import "@/lib/api-client";
import { getImportProgressImportsImportIdProgressGet } from "@/lib/api/sdk.gen";
import type { ImportProgressResponse } from "@/lib/api/types.gen";
import { errorMessage } from "@/lib/import/errors";
import { POLL_INTERVAL_MS, statusText } from "@/lib/import/progress";

import UnmatchedOwnersPanel from "@/components/import/UnmatchedOwnersPanel";

type Props = Readonly<{ importId: string; canAssign: boolean }>;

const MESSAGE_FAILED_IMPORT =
  "The import stopped because of a problem with the file or the server. Ask an administrator for help.";

/** Renders the status, the progress bar, the outcome counters and, when done, the owner panel. */
export default function ImportProgress({ importId, canAssign }: Props) {
  const [progress, setProgress] = useState<ImportProgressResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Poll until the server says the import is finished. A failed poll keeps the last numbers,
  // shows the problem and tries again on the next tick (a short outage must not end the page).
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      const result = await getImportProgressImportsImportIdProgressGet({
        path: { import_id: importId },
      });
      if (cancelled) return;
      if (result.data) {
        setProgress(result.data);
        setError(null);
        if (result.data.finished) return;
      } else {
        setError(errorMessage(result.error, result.response));
      }
      timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    }
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [importId]);

  if (!progress) {
    return error ? <p role="alert">{error}</p> : <p>Loading the import…</p>;
  }

  return (
    <section aria-labelledby="progress-title">
      <h2 id="progress-title">Import progress</h2>
      <p>
        Status: <strong>{statusText(progress.status)}</strong>
      </p>
      <progress
        max={100}
        value={progress.percent}
        aria-label="Import progress"
        aria-valuetext={`${progress.percent}%`}
      />{" "}
      <span>
        {progress.received} of {progress.row_count} rows ({progress.percent}%)
      </span>
      {error && <p role="alert">{error}</p>}

      <h3>So far</h3>
      <ul>
        <li>{progress.imported} new leads</li>
        <li>{progress.updated} leads updated</li>
        <li>{progress.unchanged} unchanged</li>
        <li>{progress.duplicates_found} possible duplicates</li>
        <li>{progress.quarantined} quarantined</li>
        <li>{progress.rejected} rejected</li>
      </ul>

      {progress.status === "failed" && <p role="alert">{MESSAGE_FAILED_IMPORT}</p>}
      {progress.finished && (
        <p>
          <Link href={`/leads/import/${importId}/report`}>View the full report</Link>
        </p>
      )}
      {progress.status === "completed" && canAssign && (
        <UnmatchedOwnersPanel importId={importId} />
      )}
    </section>
  );
}
