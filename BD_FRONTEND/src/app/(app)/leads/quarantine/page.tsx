/**
 * Quarantine screen route (task M2-B2).
 *
 * Needed so the menu link "Quarantine" opens the review list of import rows that failed
 * validation. The page only renders the client component; every rule and permission is enforced
 * by the server.
 */
import QuarantineScreen from "@/components/quality/QuarantineScreen";

/** Renders the quarantine review screen. */
export default function QuarantinePage() {
  return <QuarantineScreen />;
}
