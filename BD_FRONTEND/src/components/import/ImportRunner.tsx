"use client";

/**
 * Screen host for one import opened from its URL (task M2-A4 UI).
 *
 * Needed so a refresh, a bookmark or a shared link returns to the right place: it loads the
 * import once, picks the step from its status (not started goes back into the wizard, anything
 * else shows progress, see lib/import/progress.ts) and then moves between steps in component
 * state. Before the import starts, "Leave without importing" goes back to the upload page
 * without calling the server (the import stays resumable). It holds no business rules.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import "@/lib/api-client";
import { useCurrentUser } from "@/lib/auth-context";
import { getImportStatusImportsImportIdGet } from "@/lib/api/sdk.gen";
import { errorMessage } from "@/lib/import/errors";
import { canAssignOwners, stageForImport, type ImportStage } from "@/lib/import/progress";

import ImportProgress from "@/components/import/ImportProgress";
import MappingStep from "@/components/import/MappingStep";
import PreviewStep from "@/components/import/PreviewStep";
import ProfileStep from "@/components/import/ProfileStep";

type Props = Readonly<{ importId: string }>;

const UPLOAD_PAGE = "/leads/import";

/** Loads the import, then renders the step for its stage. */
export default function ImportRunner({ importId }: Props) {
  const user = useCurrentUser();
  const [stage, setStage] = useState<ImportStage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const result = await getImportStatusImportsImportIdGet({ path: { import_id: importId } });
      if (cancelled) return;
      if (result.data) setStage(stageForImport(result.data));
      else setError(errorMessage(result.error, result.response));
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [importId]);

  if (stage === null) {
    return error ? (
      <>
        <p role="alert">{error}</p>
        <Link href={UPLOAD_PAGE}>Back to import</Link>
      </>
    ) : (
      <p>Loading the import…</p>
    );
  }

  if (stage === "progress") {
    return <ImportProgress importId={importId} canAssign={canAssignOwners(user.role)} />;
  }

  return (
    <>
      {stage === "worksheet" && (
        <p role="alert">
          This workbook has several worksheets and none was chosen. Upload the file again to pick
          one.
        </p>
      )}
      {stage === "profile" && <ProfileStep importId={importId} onDone={() => setStage("mapping")} />}
      {stage === "mapping" && <MappingStep importId={importId} onDone={() => setStage("preview")} />}
      {stage === "preview" && (
        <PreviewStep
          importId={importId}
          onBack={() => setStage("mapping")}
          onStarted={() => setStage("progress")}
        />
      )}
      <p>
        <Link href={UPLOAD_PAGE}>Leave without importing</Link>
      </p>
    </>
  );
}
