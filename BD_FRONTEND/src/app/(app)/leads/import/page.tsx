/**
 * Import screen: hosts the import wizard (tasks M2-A1 and M2-A2 UI).
 *
 * Needed so the Import menu entry leads to upload, profile, mapping and preview; starting the
 * import arrives in M2-A3. The page only hosts the client component, which holds no business rules.
 */
import ImportWizard from "@/components/import/ImportWizard";

/** Renders the Import heading and the import wizard. */
export default function ImportPage() {
  return (
    <section>
      <h1>Import</h1>
      <ImportWizard />
    </section>
  );
}
