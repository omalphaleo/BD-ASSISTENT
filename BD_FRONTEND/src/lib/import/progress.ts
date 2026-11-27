/**
 * Display helpers for the import progress and resume screens (task M2-A4 UI).
 *
 * Needed so the polling interval, the status wording and the "which step am I on after a refresh"
 * rule live in one tested place. This is presentation only: the server owns the status, the
 * counters and who may assign owners (D-050, D-075); the role check below only decides what is shown.
 */
import type { ImportFileResponse, ImportStatus, UserRole } from "@/lib/api/types.gen";

/** How often the progress page asks the server for new counters (milliseconds). */
export const POLL_INTERVAL_MS = 3000;

/** The screen shown for an import: a wizard step, or the progress and result view. */
export type ImportStage = "profile" | "mapping" | "preview" | "progress" | "worksheet";

const STATUS_TEXT: Record<ImportStatus, string> = {
  uploaded: "Uploaded, not started",
  mapping: "Being mapped, not started",
  processing: "Importing",
  completed: "Completed",
  failed: "Failed",
};

/** Roles that see the owner assignment panel (mirrors ASSIGN_LEADS; the server enforces it). */
const ASSIGNER_ROLES: readonly UserRole[] = ["manager", "admin"];

/** Readable text for an import status. */
export function statusText(status: ImportStatus): string {
  return STATUS_TEXT[status];
}

/** True for roles that may assign owners; cosmetic, the server rejects everyone else. */
export function canAssignOwners(role: UserRole): boolean {
  return ASSIGNER_ROLES.includes(role);
}

/**
 * Picks the screen to open for an import loaded from its URL (resume after a refresh, a bookmark
 * or a shared link): not yet started goes back into the wizard, anything else shows progress.
 *
 * A workbook that still needs its worksheet chosen cannot continue here (the sheet list is only
 * returned by the upload call), so it gets its own stage that asks for a new upload.
 */
export function stageForImport(
  imported: Pick<ImportFileResponse, "status" | "worksheet" | "filename">,
): ImportStage {
  switch (imported.status) {
    case "uploaded":
    case "mapping": {
      const isWorkbook = imported.filename.toLowerCase().endsWith(".xlsx");
      return isWorkbook && imported.worksheet === null ? "worksheet" : "profile";
    }
    default:
      return "progress";
  }
}
