/**
 * Natural-language search helpers for the Leads screen (task M3-A6, plan section 9).
 *
 * Needed so the NL box has one tested place for "send the sentence, get draft filters back, or a
 * plain reason why not". The server does all the interpreting (the AI only proposes filters, the
 * app validates them); this file only calls the generated client and words the outcome. A failed
 * call never throws: the screen gets a message and structured search keeps working.
 */
import { interpretNlQuerySearchNlInterpretPost } from "@/lib/api/sdk.gen";
import type { FilterSet } from "@/lib/search/filters";

/** Longest sentence the server accepts; the input stops there so the user is never surprised. */
export const MAX_NL_QUERY_LENGTH = 500;

const MESSAGE_UNREACHABLE = "The server could not be reached. Check your connection and try again.";
const MESSAGE_FORBIDDEN = "You do not have permission to search leads.";
const MESSAGE_UNAVAILABLE = "AI search is unavailable right now. You can still use the filters.";
const MESSAGE_GENERIC = "The AI search failed. Use the filters instead, or try again later.";
const MESSAGE_TOO_LONG = "That sentence is too long. Shorten it and try again.";

/** What the NL box shows after a try: draft filters with notices, or a failure message. */
export type NlOutcome =
  | Readonly<{
      ok: true;
      filters: FilterSet;
      droppedFields: readonly string[];
      unrecognisedTerms: readonly string[];
    }>
  | Readonly<{ ok: false; message: string }>;

/** True when the sentence is worth sending: not blank and within the server's length limit. */
export function isInterpretable(query: string): boolean {
  const trimmed = query.trim();
  return trimmed.length > 0 && trimmed.length <= MAX_NL_QUERY_LENGTH;
}

/**
 * Plain-language text for a failed NL call, from the HTTP status (undefined = no answer).
 *
 * 502 and 503 carry the server's own sentence in `detail`; only a string is shown.
 */
export function describeNlFailure(status: number | undefined, error: unknown): string {
  if (status === undefined) return MESSAGE_UNREACHABLE;
  if (status === 403) return MESSAGE_FORBIDDEN;
  if (status === 422) return MESSAGE_TOO_LONG;
  if (status === 502 || status === 503) {
    const detail = (error as { detail?: unknown } | null | undefined)?.detail;
    return typeof detail === "string" && detail ? detail : MESSAGE_UNAVAILABLE;
  }
  return MESSAGE_GENERIC;
}

/**
 * The lines to show under the box about what the app did not apply: fields it refused and parts
 * of the sentence it could not map. An empty list means everything was understood.
 */
export function describeNotices(
  droppedFields: readonly string[],
  unrecognisedTerms: readonly string[],
): string[] {
  const lines: string[] = [];
  if (unrecognisedTerms.length > 0) {
    lines.push(`Not understood: ${unrecognisedTerms.join(", ")}.`);
  }
  if (droppedFields.length > 0) {
    lines.push(`Ignored (not a filter you can set this way): ${droppedFields.join(", ")}.`);
  }
  return lines;
}

/** Sends the sentence to the server and returns draft filters or a failure message. */
export async function interpretQuery(query: string): Promise<NlOutcome> {
  const result = await interpretNlQuerySearchNlInterpretPost({ body: { query: query.trim() } });
  if (!result.data) {
    return { ok: false, message: describeNlFailure(result.response?.status, result.error) };
  }
  return {
    ok: true,
    filters: result.data.filters,
    droppedFields: result.data.dropped_fields,
    unrecognisedTerms: result.data.unrecognised_terms,
  };
}
