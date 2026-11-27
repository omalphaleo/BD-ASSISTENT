/**
 * Empty shell for the lead page (task M3-0).
 *
 * Needed so a search result can already link to /leads/{personId}; the lead record, notes and
 * actions arrive in M3-B.
 */
import PlaceholderPage from "@/components/PlaceholderPage";

/** Renders the placeholder for a single lead. */
export default function LeadPage() {
  return <PlaceholderPage title="Lead" availability="The lead page arrives in M3." />;
}
