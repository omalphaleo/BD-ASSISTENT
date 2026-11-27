/**
 * Empty shell for the company page (task M3-0).
 *
 * Needed so the lead page can already link to /companies/{companyId}; the company record
 * arrives in M3-B.
 */
import PlaceholderPage from "@/components/PlaceholderPage";

/** Renders the placeholder for a single company. */
export default function CompanyPage() {
  return <PlaceholderPage title="Company" availability="The company page arrives in M3." />;
}
