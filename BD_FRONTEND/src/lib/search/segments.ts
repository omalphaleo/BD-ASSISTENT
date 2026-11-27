/**
 * Display helpers for saved segments on the Leads search page (task M3-A4).
 *
 * Needed so the wording of failures, the grouping of the list and the name check live in one
 * tested place instead of inside the panel. Presentation only: the server decides who may see or
 * change a segment (D-098), re-checks every write and answers 404 or 403 itself; nothing here
 * enforces a rule or a role.
 */
import type { SegmentResponse } from "@/lib/api/types.gen";

/** The longest segment name the server accepts (the `segments.name` column). */
export const MAX_SEGMENT_NAME_LENGTH = 255;

/** Shown where a shared segment has no owner any more (the owner's account was deleted). */
export const NO_OWNER_LABEL = "no owner";

/** The segments the caller may edit, and the ones colleagues shared that they may only apply. */
export type SegmentGroups = Readonly<{ editable: SegmentResponse[]; sharedByOthers: SegmentResponse[] }>;

/**
 * Splits the list the server returned into the caller's own segments and colleagues' shared ones.
 * The split uses the server's `can_edit` answer, so the screen never works out ownership itself.
 */
export function groupSegments(items: readonly SegmentResponse[]): SegmentGroups {
  return {
    editable: items.filter((segment) => segment.can_edit),
    sharedByOthers: items.filter((segment) => !segment.can_edit),
  };
}

/** The owner's email for a row, or "no owner" when the owner's account no longer exists. */
export function ownerLabel(segment: Pick<SegmentResponse, "owner">): string {
  return segment.owner?.email ?? NO_OWNER_LABEL;
}

/** Whether a typed name can be sent: not blank once trimmed and not over the length limit. */
export function isSaveableName(name: string): boolean {
  const trimmed = name.trim();
  return trimmed.length > 0 && trimmed.length <= MAX_SEGMENT_NAME_LENGTH;
}

/**
 * Plain-language text for a failed segment request.
 *
 * Fixed messages by status; the response body is never shown, because it could carry text the
 * user did not write.
 */
export function describeSegmentFailure(status: number | undefined): string {
  switch (status) {
    case 401:
      return "Your session has ended. Sign in again.";
    case 403:
      return "Only the owner can change this segment.";
    case 404:
      return "This segment no longer exists. The list has been refreshed.";
    case 422:
      return "The segment was not accepted. Check the name and try again.";
    default:
      return "Something went wrong with segments. Try again.";
  }
}
