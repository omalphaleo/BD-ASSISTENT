/**
 * Shared error text for the import wizard steps (task M2-A2 UI).
 *
 * Needed so every step shows the server's fixed `detail` message the same way, with one fallback
 * for a network failure and one for an unexpected response. It holds no rules, only wording.
 */
export const MESSAGE_UNREACHABLE = "Cannot reach the server. Please try again later.";
export const MESSAGE_FAILED = "The request failed. Please try again.";

/** Picks the message to show for a failed call: the server's fixed `detail`, else a fallback. */
export function errorMessage(error: unknown, response: Response | undefined): string {
  if (!response) {
    return MESSAGE_UNREACHABLE; // no response: network or CORS failure
  }
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" && detail ? detail : MESSAGE_FAILED;
}
