"use client";

/**
 * Entry of the import wizard: the upload step (tasks M2-A1, M2-A2 and M2-A4 UI).
 *
 * Needed so a finished upload moves to the import's own address, /leads/import/[importId], where
 * ImportRunner shows the profile, mapping, preview and progress steps. Giving the import a URL is
 * what lets a refresh or a shared link resume it. It holds no business rules.
 */
import { useRouter } from "next/navigation";

import UploadWizard from "@/components/import/UploadWizard";

/** Renders the upload step and opens the import's page once the file is ready. */
export default function ImportWizard() {
  const router = useRouter();
  return <UploadWizard onReady={(upload) => router.push(`/leads/import/${upload.id}`)} />;
}
