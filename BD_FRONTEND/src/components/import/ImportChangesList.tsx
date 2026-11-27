"use client";

/**
 * Paged "what changed in this import" list for the report page (task M2-A5 UI; D-050).
 *
 * Needed so a user can see, for every lead the import updated, which fields changed and from
 * what to what. The server pages the data (50 leads per page) and labels the fields; this
 * component shows them as plain text (values come from uploaded files) and only moves between
 * pages. It holds no business rules.
 */
import { useEffect, useState } from "react";

import "@/lib/api-client";
import { getImportChangesImportsImportIdChangesGet } from "@/lib/api/sdk.gen";
import type { ChangesPageResponse } from "@/lib/api/types.gen";
import { errorMessage } from "@/lib/import/errors";
import { pageCount, valueText } from "@/lib/import/report";

type Props = Readonly<{ importId: string }>;

/** Renders the changed leads of one page with Previous and Next buttons. */
export default function ImportChangesList({ importId }: Props) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<ChangesPageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const result = await getImportChangesImportsImportIdChangesGet({
        path: { import_id: importId },
        query: { page },
      });
      if (cancelled) return;
      if (result.data) {
        setData(result.data);
        setError(null);
      } else {
        setError(errorMessage(result.error, result.response));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [importId, page]);

  if (!data) {
    return error ? <p role="alert">{error}</p> : <p>Loading the changes…</p>;
  }
  if (data.total === 0) {
    return <p>This import did not change any existing lead.</p>;
  }

  const pages = pageCount(data.total, data.page_size);
  return (
    <div>
      {error && <p role="alert">{error}</p>}
      <ul aria-label="Changed leads">
        {data.items.map((lead) => (
          <li key={lead.person_id}>
            <strong>{lead.name}</strong>
            {lead.email ? ` (${lead.email})` : ""}
            <ul>
              {lead.changes.map((change) => (
                <li key={change.field}>
                  {change.label}: {valueText(change.old)} → {valueText(change.new)}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      <p>
        <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>
          Previous
        </button>{" "}
        <span>
          Page {data.page} of {pages} ({data.total} leads)
        </span>{" "}
        <button type="button" disabled={page >= pages} onClick={() => setPage(page + 1)}>
          Next
        </button>
      </p>
    </div>
  );
}
