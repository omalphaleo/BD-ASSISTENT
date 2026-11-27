/**
 * Source profiles admin screen (task M2-A6 UI).
 *
 * Needed so the Source profiles menu entry leads to the profile admin: list, create, edit,
 * activate or deactivate, and trim saved mappings. The server enforces who may use it; the page
 * only hosts the client component, which holds no business rules.
 */
import SourceProfilesAdmin from "@/components/import/SourceProfilesAdmin";

/** Renders the Source profiles heading and the admin component. */
export default function SourceProfilesPage() {
  return (
    <section>
      <h1>Source profiles</h1>
      <SourceProfilesAdmin />
    </section>
  );
}
