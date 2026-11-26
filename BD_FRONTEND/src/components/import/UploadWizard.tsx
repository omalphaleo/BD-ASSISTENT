"use client";

/**
 * Upload step of the import wizard (task M2-A1 UI).
 *
 * Needed so a user can send a CSV or XLSX file, see the duplicate-file warning (D-109) and pick
 * the worksheet of a multi-sheet workbook. It calls only the generated `/imports` client
 * functions; every decision (file type, size, duplicates, who may choose a sheet) is the
 * server's, and the component shows the server's fixed messages. Later steps (mapping, preview,
 * start) arrive with M2-A2 and are not built yet.
 */
import { useState, type FormEvent } from "react";

// Imported for its side effect: it points the generated client at the backend and adds the CSRF
// header and the 401 redirect. The generated functions are then called directly.
import "@/lib/api-client";
import {
  chooseWorksheetImportsImportIdWorksheetPost,
  uploadImportFileImportsUploadPost,
} from "@/lib/api/sdk.gen";
import type { DuplicateFileResponse, UploadResponse } from "@/lib/api/types.gen";

const ACCEPTED_FILE_TYPES = ".csv,.xlsx";
const MESSAGE_NO_FILE = "Choose a CSV or XLSX file first.";
const MESSAGE_UNREACHABLE = "Cannot reach the server. Please try again later.";
const MESSAGE_FAILED = "The request failed. Please try again.";
const DUPLICATE_CODE = "duplicate_file";

/** What the wizard is showing: the form, the duplicate warning, the picker or the result. */
type Step =
  | { kind: "form" }
  | { kind: "duplicate"; warning: DuplicateFileResponse }
  | { kind: "worksheet"; upload: UploadResponse }
  | { kind: "ready"; upload: UploadResponse };

/** Picks the message to show for a failed call: the server's fixed `detail`, else a fallback. */
function errorMessage(error: unknown, response: Response | undefined): string {
  if (!response) {
    return MESSAGE_UNREACHABLE; // no response: network or CORS failure
  }
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" && detail ? detail : MESSAGE_FAILED;
}

/** Formats an ISO timestamp for the duplicate warning (the user's locale and time zone). */
function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString();
}

/** Renders the upload form and the steps that follow it. */
export default function UploadWizard() {
  const [file, setFile] = useState<File | null>(null);
  const [step, setStep] = useState<Step>({ kind: "form" });
  const [worksheet, setWorksheet] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /** Sends the file; `allowDuplicate` is true only after the user chose "Import anyway". */
  async function upload(allowDuplicate: boolean) {
    if (!file) {
      setError(MESSAGE_NO_FILE);
      return;
    }
    setError(null);
    setBusy(true);
    const result = await uploadImportFileImportsUploadPost({
      body: { file, allow_duplicate: allowDuplicate },
    });
    setBusy(false);

    if (result.data) {
      const uploaded = result.data;
      if (uploaded.worksheet === null && uploaded.worksheets.length > 0) {
        // A multi-sheet workbook: the user must pick one before the import can continue.
        const firstSelectable = uploaded.worksheets.find((sheet) => sheet.selectable);
        setWorksheet(firstSelectable?.name ?? "");
        setStep({ kind: "worksheet", upload: uploaded });
      } else {
        setStep({ kind: "ready", upload: uploaded });
      }
      return;
    }

    const body = result.error as Partial<DuplicateFileResponse> | undefined;
    if (result.response?.status === 409 && body?.code === DUPLICATE_CODE) {
      setStep({ kind: "duplicate", warning: body as DuplicateFileResponse });
      return;
    }
    setError(errorMessage(result.error, result.response));
  }

  /** Form submit: a normal upload (never allows a duplicate). */
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void upload(false);
  }

  /** Sends the chosen worksheet for a multi-sheet workbook. */
  async function handleWorksheetSubmit(event: FormEvent<HTMLFormElement>, current: UploadResponse) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    const result = await chooseWorksheetImportsImportIdWorksheetPost({
      path: { import_id: current.id },
      body: { worksheet },
    });
    setBusy(false);

    if (result.data) {
      setStep({ kind: "ready", upload: { ...current, ...result.data } });
      return;
    }
    setError(errorMessage(result.error, result.response));
  }

  /** Back to the empty form (used by "Cancel" on the duplicate warning). */
  function reset() {
    setStep({ kind: "form" });
    setFile(null);
    setError(null);
  }

  if (step.kind === "duplicate") {
    const { warning } = step;
    return (
      <section aria-labelledby="duplicate-title">
        <h2 id="duplicate-title">This file was already uploaded</h2>
        <p>
          It was uploaded on {formatWhen(warning.earlier_uploaded_at)}
          {warning.earlier_uploaded_by ? ` by ${warning.earlier_uploaded_by}` : ""}.
        </p>
        {error && <p role="alert">{error}</p>}
        <button className="button" type="button" disabled={busy} onClick={() => void upload(true)}>
          Import anyway
        </button>{" "}
        <button className="button button-secondary" type="button" disabled={busy} onClick={reset}>
          Cancel
        </button>
      </section>
    );
  }

  if (step.kind === "worksheet") {
    const { upload: current } = step;
    return (
      <form onSubmit={(event) => void handleWorksheetSubmit(event, current)}>
        <h2>Choose a worksheet</h2>
        <p>{current.filename} has several worksheets. Pick the one to import.</p>
        <label className="field">
          <span>Worksheet</span>
          <select value={worksheet} onChange={(event) => setWorksheet(event.target.value)}>
            {current.worksheets.map((sheet) => (
              <option key={sheet.name} value={sheet.name} disabled={!sheet.selectable}>
                {sheet.name} ({sheet.row_count} rows{sheet.selectable ? "" : ", not usable"})
              </option>
            ))}
          </select>
        </label>
        {error && <p role="alert">{error}</p>}
        <button className="button" type="submit" disabled={busy || !worksheet}>
          {busy ? "Saving…" : "Use this worksheet"}
        </button>
      </form>
    );
  }

  if (step.kind === "ready") {
    const { upload: current } = step;
    return (
      <section aria-labelledby="ready-title">
        <h2 id="ready-title">File received</h2>
        <p>
          {current.filename}
          {current.worksheet ? `, worksheet ${current.worksheet}` : ""}: {current.row_count} rows.
        </p>
        <p>Column mapping, preview and start arrive in the next step (planned).</p>
        <button className="button button-secondary" type="button" onClick={reset}>
          Upload another file
        </button>
      </section>
    );
  }

  return (
    <form onSubmit={handleSubmit}>
      <label className="field">
        <span>CSV or XLSX file</span>
        <input
          type="file"
          name="file"
          accept={ACCEPTED_FILE_TYPES}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
      </label>
      {error && <p role="alert">{error}</p>}
      <button className="button" type="submit" disabled={busy}>
        {busy ? "Uploading…" : "Upload"}
      </button>
    </form>
  );
}
