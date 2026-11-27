/**
 * Report page of one import, opened by its id (task M2-A5 UI).
 *
 * Needed so the result of an import has an address: the progress view links here when the
 * import has finished, and a shared link opens the same report. The page only reads the id from
 * the URL and renders the client component, which holds no business rules.
 */
import ImportReport from "@/components/import/ImportReport";

/** Renders the Import report heading and the report for the import named in the URL. */
export default async function ImportReportPage({
  params,
}: Readonly<{ params: Promise<{ importId: string }> }>) {
  const { importId } = await params;
  return (
    <section>
      <h1>Import report</h1>
      <ImportReport importId={importId} />
    </section>
  );
}
