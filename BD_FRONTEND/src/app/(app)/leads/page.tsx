/**
 * Leads search route (task M3-A3).
 *
 * Needed so the menu link "Leads" (/leads) opens the lead search screen, replacing the M1
 * placeholder. The page only renders the client component; every rule and permission is
 * enforced by the server.
 */
import SearchScreen from "@/components/search/SearchScreen";

/** Renders the Leads search screen. */
export default function LeadsPage() {
  return <SearchScreen />;
}
