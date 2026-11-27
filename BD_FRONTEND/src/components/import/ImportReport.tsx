"use client";

/**
 * Report of a finished import: totals, why rows failed, what changed, downloads (task M2-A5 UI).
 *
 * Needed so the user can trust an import's result (D-050): the seven totals, the reason-coded
 * failures, a list of the leads that were updated and CSV downloads of the rejected and
 * quarantined rows and of the changes (D-111). Everything shown is what the server returns; the
 * server also decides who may download and writes the audit event, so a refusal is shown as the
 * server's message. File content comes from uploads, so it is rendered as plain text only.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import "@/lib/api-client";
import {
  downloadChangesImportsImportIdDownloadChangesCsvGet,
  downloadFailedRowsImportsImportIdDownloadFailedRowsCsvGet,
  getImportReportImportsImportIdReportGet,
} from "@/lib/api/sdk.gen";
import type { ImportReportResponse } from "@/lib/api/types.gen";
import { errorMessage } from "@/lib/import/errors";
import { reasonText, saveCsvResult, type CsvKind } from "@/lib/import/report";
import { statusText } from "@/lib/import/progress";

import ImportChangesList from "@/components/import/ImportChangesList";

type Props = Readonly<{ importId: string }>;

const MESSAGE_FAILED_IMPORT =
  "This import stopped before the end, so the numbers below cover only the rows handled so far.";

/** Renders the report, or the server's message when it is not available (for example not finished). */
export default function ImportReport({ importId }: Props) {
  const [report, setReport] = useState<ImportReportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<CsvKind | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const result = await getImportReportImportsImportIdReportGet({
        path: { import_id: importId },
      });
      if (cancelled) return;
      if (result.data) setReport(result.data);
      else setError(errorMessage(result.error, result.response));
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [importId]);

  async function download(kind: CsvKind) {
    setBusy(kind);
    setDownloadError(null);
    const options = { path: { import_id: importId }, parseAs: "blob" as const };
    const result =
      kind === "failed-rows"
        ? await downloadFailedRowsImportsImportIdDownloadFailedRowsCsvGet(options)
        : await downloadChangesImportsImportIdDownloadChangesCsvGet(options);
    setDownloadError(saveCsvResult(result, importId, kind));
    setBusy(null);
  }

  const back = <Link href={`/leads/import/${importId}`}>Back to the import</Link>;
  if (!report) {
    return error ? (
      <>
        <p role="alert">{error}</p>
        <p>{back}</p>
      </>
    ) : (
      <p>Loading the report…</p>
    );
  }

  const failedTotal = report.quarantined + report.rejected;
  return (
    <section aria-labelledby="report-title">
      <h2 id="report-title">Import report</h2>
      <p>
        {report.filename} — <strong>{statusText(report.status)}</strong>
      </p>
      {report.status === "failed" && <p role="alert">{MESSAGE_FAILED_IMPORT}</p>}

      <h3>Totals</h3>
      <ul>
        <li>{report.received} rows received</li>
        <li>{report.imported} new leads</li>
        <li>{report.updated} leads updated</li>
        <li>{report.unchanged} unchanged</li>
        <li>{report.duplicates_found} possible duplicates</li>
        <li>{report.quarantined} quarantined</li>
        <li>{report.rejected} rejected</li>
      </ul>

      <h3>Why rows failed</h3>
      {report.failure_reasons.length === 0 ? (
        <p>No row was rejected or quarantined.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">Reason</th>
              <th scope="col">Rows</th>
            </tr>
          </thead>
          <tbody>
            {report.failure_reasons.map((reason) => (
              <tr key={reason.code}>
                <td>{reasonText(reason.code)}</td>
                <td>{reason.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>Downloads</h3>
      <p>
        <button
          type="button"
          disabled={busy !== null || failedTotal === 0}
          onClick={() => void download("failed-rows")}
        >
          Download failed and quarantined rows (CSV)
        </button>{" "}
        <button
          type="button"
          disabled={busy !== null || report.changes_total === 0}
          onClick={() => void download("changes")}
        >
          Download changes (CSV)
        </button>
      </p>
      {downloadError && <p role="alert">{downloadError}</p>}

      <h3>What changed in this import</h3>
      <ImportChangesList importId={importId} />

      <p>{back}</p>
    </section>
  );
}
