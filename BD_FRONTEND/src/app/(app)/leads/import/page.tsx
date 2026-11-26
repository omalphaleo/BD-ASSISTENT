/**
 * Import screen: the upload step of the wizard (task M2-A1 UI).
 *
 * Needed so the Import menu entry leads to a working upload; the later wizard steps arrive in
 * M2-A2 and M2-A3. The page only hosts the client component, which holds no business rules.
 */
import UploadWizard from "@/components/import/UploadWizard";

/** Renders the Import heading and the upload wizard. */
export default function ImportPage() {
  return (
    <section>
      <h1>Import</h1>
      <UploadWizard />
    </section>
  );
}
