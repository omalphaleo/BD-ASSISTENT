/**
 * Display helpers and the CSV download for the import report screens (task M2-A5 UI; D-050, D-111).
 *
 * Needed so the wording of reason codes and empty values, and the "fetch a CSV and save it" step,
 * live in one tested place. Presentation only: the server owns the totals, the reasons, who may
 * download and the audit of each download. A download goes through the generated client (so it
 * carries the session cookie) and is saved from an in-memory blob, never a plain link.
 */
import { errorMessage } from "@/lib/import/errors";

/** Server reason codes with a fixed, friendlier wording; any other code is shown spaced out. */
const REASON_TEXT: Record<string, string> = {
  ingest_error: "Unexpected error while processing the row",
  unspecified: "No reason given",
};

/** Text for a cell value in the change list: empty values read as "(empty)". */
export const EMPTY_VALUE_TEXT = "(empty)";

/** Readable text for a failure reason code (for example "personal_email_only"). */
export function reasonText(code: string): string {
  return REASON_TEXT[code] ?? code.replaceAll("_", " ");
}

/** Text for an old or new value of a changed field. */
export function valueText(value: string | number | boolean | null): string {
  return value === null || value === "" ? EMPTY_VALUE_TEXT : String(value);
}

/** Number of pages for a total (never below 1, so an empty list still has "page 1 of 1"). */
export function pageCount(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / pageSize));
}

/** The kinds of CSV a report can download; the file name is built from the import and the kind. */
export type CsvKind = "failed-rows" | "changes";

/** The shape of a generated-client result for a call made with `parseAs: "blob"`. */
type BlobResult = Readonly<{ data?: unknown; error?: unknown; response?: Response }>;

/**
 * Saves the CSV of a finished download call, or returns the message to show.
 *
 * Args:
 *   result: what the generated function returned (called with parseAs "blob").
 *   importId: the import, used in the file name (never lead data).
 *   kind: which file this is.
 *
 * Returns:
 *   null when the file was handed to the browser, otherwise the error text.
 */
export function saveCsvResult(result: BlobResult, importId: string, kind: CsvKind): string | null {
  if (!(result.data instanceof Blob)) {
    return errorMessage(result.error, result.response);
  }
  const url = URL.createObjectURL(result.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = `import-${importId}-${kind}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  return null;
}
