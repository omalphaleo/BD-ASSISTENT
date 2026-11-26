/**
 * Duplicates screen route (task M2-B5).
 *
 * Needed so the menu link "Duplicates" opens the review of possible duplicate people. The page
 * only renders the client component; every rule and permission is enforced by the server.
 */
import DuplicatesScreen from "@/components/quality/DuplicatesScreen";

/** Renders the duplicate review screen. */
export default function DuplicatesPage() {
  return <DuplicatesScreen />;
}
