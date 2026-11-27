"use client";

/**
 * Preview and estimate step of the import wizard (task M2-A2 UI; D-068, D-069).
 *
 * Needed so the uploader can check the first rows as the saved mapping reads them, see cells that
 * could not be converted, and see what the file itself implies (row counts, rows without the
 * mandatory fields, unmapped columns) before starting. "Start import" (M2-A4 UI) asks the server
 * to start the job and is enabled only when the server's estimate says the import can start; the
 * server still checks that the caller is the uploader. Numbers and warnings come from the server.
 */
import { useEffect, useState } from "react";

import "@/lib/api-client";
import {
  readEstimateImportsImportIdEstimateGet,
  readPreviewImportsImportIdPreviewGet,
  startImportProcessingImportsImportIdStartPost,
} from "@/lib/api/sdk.gen";
import type { EstimateResponse, PreviewResponse } from "@/lib/api/types.gen";
import { errorMessage } from "@/lib/import/errors";
import { blockingIssueText, warningText } from "@/lib/import/messages";

type Props = Readonly<{ importId: string; onBack: () => void; onStarted: () => void }>;

const NO_HEADER = "(no header)";

/** Renders the preview table, the estimate panel and the start button. */
export default function PreviewStep({ importId, onBack, onStarted }: Props) {
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [estimate, setEstimate] = useState<EstimateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [rows, counts] = await Promise.all([
        readPreviewImportsImportIdPreviewGet({ path: { import_id: importId } }),
        readEstimateImportsImportIdEstimateGet({ path: { import_id: importId } }),
      ]);
      if (cancelled) return;
      if (rows.data && counts.data) {
        setPreview(rows.data);
        setEstimate(counts.data);
      } else {
        const failed = rows.data ? counts : rows;
        setError(errorMessage(failed.error, failed.response));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [importId]);

  /** Asks the server to start the import (uploader only); the host then shows the progress. */
  async function handleStart() {
    setStartError(null);
    setStarting(true);
    const result = await startImportProcessingImportsImportIdStartPost({
      path: { import_id: importId },
    });
    setStarting(false);
    if (result.data) {
      onStarted();
      return;
    }
    setStartError(errorMessage(result.error, result.response));
  }

  if (!preview || !estimate) {
    return error ? <p role="alert">{error}</p> : <p>Loading the preview…</p>;
  }

  // Columns shown: every mapped field that appears in the preview rows, in first-seen order.
  const keys = [...new Set(preview.rows.flatMap((row) => Object.keys(row.values)))];
  const warningEntries = Object.entries(estimate.warning_counts);

  return (
    <section aria-labelledby="preview-title">
      <h2 id="preview-title">Preview and estimate</h2>

      <h3>First {preview.rows.length} rows</h3>
      <table>
        <thead>
          <tr>
            <th scope="col">Row</th>
            {keys.map((key) => (
              <th scope="col" key={key}>
                {key}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {preview.rows.map((row) => (
            <tr key={row.row_number}>
              <th scope="row">{row.row_number}</th>
              {keys.map((key) => {
                const warning = row.warnings.find((w) => w.field === key);
                const value = row.values[key];
                return (
                  <td key={key}>
                    {value === null || value === undefined ? "" : String(value)}
                    {warning && <mark> {warningText(warning.code)}</mark>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Estimate</h3>
      <ul>
        <li>{estimate.rows_total} rows in the file</li>
        <li>{estimate.rows_without_email} rows without an email</li>
        <li>{estimate.rows_without_first_name} rows without a first name</li>
        {warningEntries.map(([field, count]) => (
          <li key={field}>
            {count} cells in {field} could not be converted
          </li>
        ))}
      </ul>
      {estimate.unmapped_columns.length > 0 && (
        <p>
          Not mapped (kept in the raw rows):{" "}
          {estimate.unmapped_columns.map((c) => c.source_header || NO_HEADER).join(", ")}
        </p>
      )}
      {estimate.blocking_issues.length > 0 && (
        <ul role="alert">
          {estimate.blocking_issues.map((code) => (
            <li key={code}>{blockingIssueText(code)}</li>
          ))}
        </ul>
      )}

      <button className="button button-secondary" type="button" onClick={onBack}>
        Back to mapping
      </button>{" "}
      {startError && <p role="alert">{startError}</p>}
      <button
        className="button"
        type="button"
        disabled={!estimate.can_start || starting}
        onClick={() => void handleStart()}
      >
        {starting ? "Starting…" : "Start import"}
      </button>
    </section>
  );
}
