/**
 * The CSV export of lead search results (task M3-A5, D-087).
 *
 * Needed so the "Export CSV" button has one tested place for "ask the server for the file and
 * save it". The server decides who may export, builds the file, neutralises formula injection and
 * writes the audit event; this file only sends the current filter and hands the answer to the
 * browser from an in-memory blob (through the generated client, so the session cookie and CSRF
 * token go along; never a plain link).
 */
import { exportLeadsSearchLeadsExportCsvPost } from "@/lib/api/sdk.gen";
import type { SortDirection, SortField } from "@/lib/api/types.gen";
import type { FilterSet } from "@/lib/search/filters";

/** File name used when the server's Content-Disposition header cannot be read. */
export const FALLBACK_FILE_NAME = "leads.csv";

const MESSAGE_UNREACHABLE = "Cannot reach the server. Please try again later.";
const MESSAGE_FORBIDDEN = "You are not allowed to export leads.";
const MESSAGE_GENERIC = "The export failed. Try again, and tell an admin if it keeps happening.";

/** The shape of a generated-client result for a call made with `parseAs: "blob"`. */
type BlobResult = Readonly<{ data?: unknown; error?: unknown; response?: Response }>;

/** Reads the file name from a Content-Disposition header such as `attachment; filename="x.csv"`. */
export function fileNameFrom(header: string | null | undefined): string {
  const match = header ? /filename="([^"]+)"/.exec(header) : null;
  return match ? match[1] : FALLBACK_FILE_NAME;
}

/**
 * Plain-language text for a failed export.
 *
 * A 422 carries the server's own sentence (for example "3000 leads match; one export holds at most
 * 50000. Narrow the filters."); only a string `detail` is shown, anything else gets the generic text.
 */
export function describeExportFailure(
  status: number | undefined,
  error: unknown,
): string {
  if (status === undefined) return MESSAGE_UNREACHABLE;
  if (status === 403) return MESSAGE_FORBIDDEN;
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (status === 422 && typeof detail === "string" && detail) return detail;
  return MESSAGE_GENERIC;
}

/**
 * Saves the CSV of a finished export call, or returns the message to show.
 *
 * Returns:
 *   null when the file was handed to the browser, otherwise the error text.
 */
export function saveExportResult(result: BlobResult): string | null {
  if (!(result.data instanceof Blob)) {
    return describeExportFailure(result.response?.status, result.error);
  }
  const url = URL.createObjectURL(result.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileNameFrom(result.response?.headers.get("content-disposition"));
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  return null;
}

/**
 * Exports every lead matching the filters (never only the ticked rows) and saves the file.
 *
 * Returns:
 *   null on success, otherwise the message to show.
 */
export async function exportLeadsCsv(
  filters: FilterSet,
  sort: SortField,
  direction: SortDirection,
): Promise<string | null> {
  const result = await exportLeadsSearchLeadsExportCsvPost({
    body: { filters, sort, direction },
    parseAs: "blob",
  });
  return saveExportResult(result);
}
