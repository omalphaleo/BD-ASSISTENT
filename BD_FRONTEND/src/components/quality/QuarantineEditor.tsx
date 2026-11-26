"use client";

/**
 * Inline editor for one quarantined row (task M2-B2).
 *
 * Needed so BD can correct a row, for example add a work email, before releasing it. It shows
 * the four fields validation reads plus any other value the file carried, and hands only the
 * changed fields to the screen, which sends them to the server. The server validates the values
 * and refreshes the reason codes; nothing is validated here.
 */
import { useState, type FormEvent } from "react";

import type { QuarantineRecordResponse } from "@/lib/api-client";
import { EDITABLE_FIELDS, changedValues, displayValue } from "@/lib/quality/quarantine";

const MESSAGE_NO_CHANGES = "Nothing was changed.";

type EditorProps = Readonly<{
  record: QuarantineRecordResponse;
  saving: boolean;
  onSave: (changes: Record<string, string>) => void;
  onCancel: () => void;
}>;

/** Builds the starting text of every input from the row's current values. */
function initialValues(payload: QuarantineRecordResponse["payload"]): Record<string, string> {
  const values: Record<string, string> = {};
  for (const { name } of EDITABLE_FIELDS) {
    values[name] = displayValue(payload[name]);
  }
  for (const [name, value] of Object.entries(payload)) {
    values[name] = displayValue(value);
  }
  return values;
}

/** Renders the edit form; "Save changes" sends only the fields that differ. */
export default function QuarantineEditor({ record, saving, onSave, onCancel }: EditorProps) {
  const [values, setValues] = useState(() => initialValues(record.payload));
  const [message, setMessage] = useState<string | null>(null);

  const knownNames = new Set(EDITABLE_FIELDS.map((field) => field.name));
  const extraNames = Object.keys(values).filter((name) => !knownNames.has(name));
  const fields = [
    ...EDITABLE_FIELDS,
    ...extraNames.map((name) => ({ name, label: name.replaceAll("_", " ") })),
  ];

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const changes = changedValues(record.payload, values);
    if (Object.keys(changes).length === 0) {
      setMessage(MESSAGE_NO_CHANGES);
      return;
    }
    setMessage(null);
    onSave(changes);
  }

  return (
    <form className="quarantine-editor" onSubmit={handleSubmit} aria-label="Edit quarantined row">
      <div className="quarantine-editor-fields">
        {fields.map(({ name, label }) => (
          <label className="field" key={name}>
            <span>{label}</span>
            <input
              type="text"
              name={name}
              value={values[name] ?? ""}
              onChange={(event) => setValues({ ...values, [name]: event.target.value })}
              disabled={saving}
            />
          </label>
        ))}
      </div>
      {message && (
        <p className="form-error" role="alert">
          {message}
        </p>
      )}
      <div className="row-actions">
        <button className="button" type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save changes"}
        </button>
        <button className="button button-secondary" type="button" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
      </div>
    </form>
  );
}
