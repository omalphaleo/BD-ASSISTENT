"use client";

/**
 * The "Export CSV" button of the Leads search page (task M3-A5, D-087).
 *
 * Needed so BD can download the leads of the current filter, as they could from Apollo (D-024).
 * It always exports the whole applied filter, not the ticked rows, and shows the server's message
 * when the export is refused (too many leads, no permission). Holds no rule: the server builds the
 * file, neutralises formula injection and audits the download.
 */
import { useState } from "react";

import styles from "@/components/search/search.module.css";
import type { SortDirection, SortField } from "@/lib/api/types.gen";
import { exportLeadsCsv } from "@/lib/search/export";
import type { FilterSet } from "@/lib/search/filters";

type Props = Readonly<{
  /** The applied filters (not the draft being edited). */
  filters: FilterSet;
  sort: SortField;
  direction: SortDirection;
  /** True when nothing matches, so there is nothing to export. */
  disabled: boolean;
}>;

/** Renders the button and, below it, the reason an export was refused. */
export default function ExportButton({ filters, sort, direction, disabled }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function exportFile() {
    setBusy(true);
    setError(null);
    setError(await exportLeadsCsv(filters, sort, direction));
    setBusy(false);
  }

  return (
    <div>
      <button
        className={styles.secondary}
        type="button"
        disabled={disabled || busy}
        onClick={() => void exportFile()}
      >
        {busy ? "Exporting…" : "Export CSV"}
      </button>
      {error && (
        <p className={styles.notice} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
