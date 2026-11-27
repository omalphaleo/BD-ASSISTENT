/**
 * Display wording for the stable codes the mapping, preview and estimate endpoints return.
 *
 * Needed so the wizard shows readable text instead of raw codes. This is presentation only: the
 * server decides what blocks an import and which cells warn (D-068, D-069); unknown codes fall
 * back to the code itself so a new server code is still visible.
 */
const BLOCKING_ISSUES: Record<string, string> = {
  email_not_mapped: "No column is mapped to Email. Map one to continue.",
  first_name_not_mapped: "No column is mapped to First name. Map one to continue.",
};

const WARNINGS: Record<string, string> = {
  not_an_integer: "Not a whole number",
  not_a_number: "Not a number",
  not_a_boolean: "Not yes or no",
  not_a_date: "Not a date",
};

const ORIGINS: Record<string, string> = {
  saved: "Saved",
  profile: "Profile",
  builtin: "Built-in",
  unmapped: "Not mapped",
};

/** Readable text for a blocking-issue code. */
export function blockingIssueText(code: string): string {
  return BLOCKING_ISSUES[code] ?? code;
}

/** Readable text for a cell-warning code. */
export function warningText(code: string): string {
  return WARNINGS[code] ?? code;
}

/** Readable label for where a mapping suggestion came from. */
export function originText(origin: string): string {
  return ORIGINS[origin] ?? origin;
}
