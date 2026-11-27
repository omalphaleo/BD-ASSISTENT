/**
 * One import, opened by its id: wizard step, progress or result (task M2-A4 UI).
 *
 * Needed so the import has an address: refreshing the page or opening a shared link returns to the
 * right step (the host picks it from the import's status). The page only reads the id from the
 * URL and renders the client component, which holds no business rules.
 */
import ImportRunner from "@/components/import/ImportRunner";

/** Renders the Import heading and the host for the import named in the URL. */
export default async function ImportPage({
  params,
}: Readonly<{ params: Promise<{ importId: string }> }>) {
  const { importId } = await params;
  return (
    <section>
      <h1>Import</h1>
      <ImportRunner importId={importId} />
    </section>
  );
}
