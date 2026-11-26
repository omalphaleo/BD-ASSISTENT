/**
 * Display helpers for the duplicate-review and mapping-admin screens (tasks M2-B5 and M2-B6).
 *
 * Needed so the wording of field labels and error messages, and the "what do we send" rules of
 * the merge form, live in one tested place instead of inside the components. Presentation
 * only: the server decides who may review or edit, which side holds the newest value and what
 * a merge does (milestone/m2.md section 19), so nothing here checks a role or a rule. It only
 * turns the server's answers into readable text and builds request bodies.
 */
import type { DuplicateCandidateResponse } from "@/lib/api-client";
import { readDetail } from "@/lib/quality/quarantine";

/** The actions the two screens can fail at. */
export type ReviewAction = "load" | "save" | "merge" | "decide";

/** Which record of a pair: "a" or "b", as the server names them. */
export type Side = "a" | "b";

/** Readable names for the person fields the server lets a merge choose. */
export const FIELD_LABELS: Record<string, string> = {
  first_name: "First name",
  last_name: "Last name",
  title: "Job title",
  seniority: "Seniority",
  department: "Department",
  city: "City",
  state: "State",
  country: "Country",
  timezone: "Time zone",
  source_status: "Source status",
  source_stage: "Source stage",
  linkedin_url: "LinkedIn",
  source_record_id: "Source record ID",
};

const MESSAGE_FORBIDDEN = "Not permitted: the server did not allow this action for your account.";
const MESSAGE_NOT_FOUND = "This item no longer exists. The list was refreshed.";
const MESSAGE_CONFLICT_DEFAULT = "This item was already decided or already exists.";
const MESSAGE_UNREACHABLE = "Cannot reach the server. Please try again later.";
const MESSAGE_GENERIC = "Something went wrong. Please try again.";

/** Returns the readable label of a field name, or the name itself if it is not known yet. */
export function fieldLabel(name: string): string {
  return FIELD_LABELS[name] ?? name.replaceAll("_", " ");
}

/**
 * Builds the message shown for a failed call.
 *
 * `status` is the HTTP status, or undefined when no answer arrived. The server's fixed `detail`
 * text is used when there is one, because it never contains lead data.
 */
export function describeReviewFailure(status: number | undefined, error?: unknown): string {
  if (status === undefined) return MESSAGE_UNREACHABLE;
  if (status === 403) return MESSAGE_FORBIDDEN;
  if (status === 404) return MESSAGE_NOT_FOUND;
  if (status === 409) return readDetail(error) ?? MESSAGE_CONFLICT_DEFAULT;
  if (status === 422) {
    const detail = readDetail(error);
    return detail ? `Some values are not acceptable: ${detail}` : MESSAGE_GENERIC;
  }
  return MESSAGE_GENERIC;
}

/** One line naming a person of a pair: "Jane Doe · jane@acme.com". */
export function personSummary(card: DuplicateCandidateResponse["person_a"]): string {
  const name = [card.fields.first_name, card.fields.last_name].filter(Boolean).join(" ");
  const email = card.emails[0];
  return [name || "(no name)", email].filter(Boolean).join(" · ");
}

/** Returns the value the server pre-selected for each field, as the starting text of the form. */
export function suggestedTexts(pair: DuplicateCandidateResponse): Record<string, string> {
  const texts: Record<string, string> = {};
  for (const [field, side] of Object.entries(pair.suggested)) {
    const card = side === "a" ? pair.person_a : pair.person_b;
    texts[field] = card.fields[field] ?? "";
  }
  return texts;
}

/** Which record's value the text currently equals, or null when it was edited to something else. */
export function pickedSide(pair: DuplicateCandidateResponse, field: string, text: string): Side | null {
  if (text === (pair.person_a.fields[field] ?? "")) return "a";
  if (text === (pair.person_b.fields[field] ?? "")) return "b";
  return null;
}

/** Keeps only non-blank texts: a blank never erases data, so it is not sent as a choice. */
export function mergeValues(texts: Record<string, string>): Record<string, string> {
  const values: Record<string, string> = {};
  for (const [field, text] of Object.entries(texts)) {
    if (text.trim() !== "") values[field] = text.trim();
  }
  return values;
}
