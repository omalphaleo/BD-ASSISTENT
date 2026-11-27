"use client";

/**
 * Host of the import wizard: upload, profile, mapping, preview (tasks M2-A1 and M2-A2 UI).
 *
 * Needed so the steps share the current import id and move in the agreed order (profile first so
 * its defaults drive the mapping suggestions). The state lives in this component only; resuming
 * after a page refresh is planned for M2-A4. It holds no business rules.
 */
import { useState } from "react";

import MappingStep from "@/components/import/MappingStep";
import PreviewStep from "@/components/import/PreviewStep";
import ProfileStep from "@/components/import/ProfileStep";
import UploadWizard from "@/components/import/UploadWizard";

type Stage = "upload" | "profile" | "mapping" | "preview";

/** Renders the step for the current stage of the import. */
export default function ImportWizard() {
  const [stage, setStage] = useState<Stage>("upload");
  const [importId, setImportId] = useState<string | null>(null);

  if (stage === "profile" && importId) {
    return <ProfileStep importId={importId} onDone={() => setStage("mapping")} />;
  }
  if (stage === "mapping" && importId) {
    return <MappingStep importId={importId} onDone={() => setStage("preview")} />;
  }
  if (stage === "preview" && importId) {
    return <PreviewStep importId={importId} onBack={() => setStage("mapping")} />;
  }
  return (
    <UploadWizard
      onReady={(upload) => {
        setImportId(upload.id);
        setStage("profile");
      }}
    />
  );
}
