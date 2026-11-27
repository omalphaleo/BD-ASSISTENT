/**
 * Display helpers for the quarantine screen (task M2-B2).
 *
 * Needed so the wording of reason codes, filters and error messages lives in one tested place
 * instead of inside the components. These are presentation only: the server decides which rows
 * are quarantined, who may act, and what an answer means (milestone/m2.md section 19), so
 * nothing here checks a role or a rule. It only turns the server's answers into readable text.
 */
import type { QuarantineRecordResponse, QuarantineStatusFilter, RowIssue } from "@/lib/api-client";

/** The four things a user can do with a quarantined row. */
export type QuarantineAction = "load" | "save" | "release" | "discard";

/** Plain-language text for each reason code the server can attach to a row. */
export const ISSUE_LABELS: Record<RowIssue, string> = {
  no_work_email: "No email address",
  personal_email_only: "Only a personal email",
  generic_email_only: "Only a generic email (info@, sales@…)",
  bad_email_format: "Email is badly formatted",
  missing_first_name: "First name is missing",
};

/** Options of the status filter, in display order (the first is the default). */
export const STATUS_OPTIONS: ReadonlyArray<{ value: QuarantineStatusFilter; label: string }> = [
  { value: "open", label: "Open" },
  { value: "released", label: "Released" },
  { value: "discarded", label: "Discarded" },
  { value: "all", label: "All" },
];

/** Options of the reason filter; the empty value means "any reason". */
export const ISSUE_OPTIONS: ReadonlyArray<{ value: RowIssue | ""; label: string }> = [
  { value: "", label: "Any reason" },
  ...(Object.keys(ISSUE_LABELS) as RowIssue[]).map((code) => ({
    value: code,
    label: ISSUE_LABELS[code],
  })),
];

/**
 * Fields the editor always offers, even when the file had no value, so BD can add what is
 * missing (for example a work email). The names are the ones the server's validation reads.
 */
export const EDITABLE_FIELDS: ReadonlyArray<{ name: string; label: string }> = [
  { name: "first_name", label: "First name" },
  { name: "email", label: "Email" },
  { name: "secondary_email", label: "Secondary email" },
  { name: "tertiary_email", label: "Tertiary email" },
];

/** Shown when releasing answers 503: the row is valid but the import step is not built yet. */
export const MESSAGE_RELEASE_UNAVAILABLE =
  "This row passes validation, but releasing it is not available yet: the step that creates " +
  "the lead has not been built (planned task M2-B4). The row stays in quarantine and nothing " +
  "was changed. Try again after that step is released.";

const MESSAGE_FORBIDDEN = "Not permitted: the server did not allow this action for your account.";
const MESSAGE_NOT_FOUND = "This record no longer exists. The list was refreshed.";
const MESSAGE_CONFLICT = "This record was already released or discarded.";
const MESSAGE_UNREACHABLE = "Cannot reach the server. Please try again later.";
const MESSAGE_GENERIC = "Something went wrong. Please try again.";

/** Returns the readable text of a reason code, or the code itself if it is not known yet. */
export function issueLabel(code: string): string {
  return code in ISSUE_LABELS ? ISSUE_LABELS[code as RowIssue] : code;
}

/** Turns a payload value (text, number, boolean or null) into the text shown in an input. */
export function displayValue(value: string | number | boolean | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

/**
 * Returns only the fields whose text differs from the stored value.
 *
 * The server needs at least one field and a blank text clears a field, so the editor sends just
 * the changes. A field the row never had that is left blank counts as unchanged.
 */
export function changedValues(
  original: QuarantineRecordResponse["payload"],
  edited: Record<string, string>,
): Record<string, string> {
  const changes: Record<string, string> = {};
  for (const [name, text] of Object.entries(edited)) {
    if (text.trim() !== displayValue(original[name]).trim()) {
      changes[name] = text;
    }
  }
  return changes;
}

/** Reads the server's `detail` text when it is a plain string; the 422 list form gives its msgs. */
export function readDetail(error: unknown): string | null {
  const detail = (error as { detail?: unknown } | null | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item as { msg?: unknown } | null)?.msg)
      .filter((msg): msg is string => typeof msg === "string");
    return messages.length > 0 ? messages.join(" ") : null;
  }
  return null;
}

/**
 * Builds the message shown for a failed call.
 *
 * `status` is the HTTP status, or undefined when no answer arrived (network or CORS failure).
 * The server's fixed `detail` text is used when there is one, because it never contains row data.
 * A 503 on release gets the dedicated "not available yet" text.
 */
export function describeFailure(
  action: QuarantineAction,
  status: number | undefined,
  error?: unknown,
): string {
  if (status === undefined) return MESSAGE_UNREACHABLE;
  if (status === 503 && action === "release") return MESSAGE_RELEASE_UNAVAILABLE;
  if (status === 403) return MESSAGE_FORBIDDEN;
  if (status === 404) return MESSAGE_NOT_FOUND;
  if (status === 409) return readDetail(error) ?? MESSAGE_CONFLICT;
  if (status === 422) {
    const detail = readDetail(error);
    return detail ? `Some values are not acceptable: ${detail}` : MESSAGE_GENERIC;
  }
  return MESSAGE_GENERIC;
}

/** What the screen says after a release attempt that the server answered with 200. */
export function describeReleaseResult(released: boolean, issues: string[]): string {
  if (released) return "Row released: it is now in the lead database.";
  if (issues.length === 0) {
    return "The row was not released. The import step still refused it; see the reasons in the list.";
  }
  return `Not released yet. Still to fix: ${issues.map(issueLabel).join("; ")}.`;
}
