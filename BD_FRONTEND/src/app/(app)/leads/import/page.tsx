/**
 * Import screen: hosts the upload step (tasks M2-A1 and M2-A4 UI).
 *
 * Needed so the Import menu entry leads to the upload; once a file is ready the browser moves to
 * /leads/import/[importId], which shows profile, mapping, preview and progress. The page only
 * hosts the client component, which holds no business rules.
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
