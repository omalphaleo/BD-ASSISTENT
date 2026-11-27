"use client";

/**
 * Side-by-side comparison of two possible duplicate people, with the merge editor (task M2-B5).
 *
 * Needed so a manager can see both records, pick or type the value to keep for every field (the
 * server pre-selects the most recent one) and merge, or say the two are different people. It
 * decides nothing: it sends the survivor and the chosen texts, and the screen shows the
 * server's answer. Both actions need a second click to confirm.
 */
import { useState } from "react";

import type { DuplicateCandidateResponse } from "@/lib/api-client";
import {
  fieldLabel,
  mergeValues,
  pickedSide,
  suggestedTexts,
  type Side,
} from "@/lib/quality/review";

type CompareProps = Readonly<{
  pair: DuplicateCandidateResponse;
  busy: boolean;
  onMerge: (survivorId: string, values: Record<string, string>) => void;
  onNotDuplicate: () => void;
  onClose: () => void;
}>;

type Confirming = "merge" | "distinct" | null;

/** Renders the comparison table, the survivor choice and the two decision buttons. */
export default function DuplicateCompare({ pair, busy, onMerge, onNotDuplicate, onClose }: CompareProps) {
  const [texts, setTexts] = useState(() => suggestedTexts(pair));
  const [survivor, setSurvivor] = useState<Side>("a");
  const [confirming, setConfirming] = useState<Confirming>(null);

  const fields = Object.keys(pair.suggested);
  const survivorId = survivor === "a" ? pair.person_a.id : pair.person_b.id;

  return (
    <div className="duplicate-compare">
      <table className="data-table">
        <caption className="visually-hidden">Compare the two records field by field</caption>
        <thead>
          <tr>
            <th scope="col">Field</th>
            <th scope="col">Record A</th>
            <th scope="col">Record B</th>
            <th scope="col">Value to keep</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((field) => {
            const picked = pickedSide(pair, field, texts[field] ?? "");
            const label = fieldLabel(field);
            return (
              <tr key={field}>
                <th scope="row">{label}</th>
                {(["a", "b"] as const).map((side) => {
                  const value = (side === "a" ? pair.person_a : pair.person_b).fields[field] ?? "";
                  return (
                    <td key={side}>
                      <label>
                        <input
                          type="radio"
                          name={`pick-${field}`}
                          checked={picked === side}
                          disabled={busy || value === ""}
                          onChange={() => setTexts({ ...texts, [field]: value })}
                          aria-label={`Use record ${side.toUpperCase()} ${label}`}
                        />{" "}
                        {value || <span className="muted">(empty)</span>}
                      </label>
                    </td>
                  );
                })}
                <td>
                  <input
                    type="text"
                    value={texts[field] ?? ""}
                    disabled={busy}
                    onChange={(event) => setTexts({ ...texts, [field]: event.target.value })}
                    aria-label={`Value to keep for ${label}`}
                  />
                </td>
              </tr>
            );
          })}
          <tr>
            <th scope="row">Email addresses</th>
            <td>{pair.person_a.emails.join(", ") || <span className="muted">(none)</span>}</td>
            <td>{pair.person_b.emails.join(", ") || <span className="muted">(none)</span>}</td>
            <td className="muted">All addresses of both records are kept.</td>
          </tr>
          <tr>
            <th scope="row">Company</th>
            <td>{pair.person_a.company_name ?? <span className="muted">(none)</span>}</td>
            <td>{pair.person_b.company_name ?? <span className="muted">(none)</span>}</td>
            <td className="muted">History from both records is combined.</td>
          </tr>
        </tbody>
      </table>

      <fieldset className="duplicate-survivor" disabled={busy}>
        <legend>Which record is kept?</legend>
        {(["a", "b"] as const).map((side) => (
          <label key={side}>
            <input
              type="radio"
              name="survivor"
              checked={survivor === side}
              onChange={() => setSurvivor(side)}
            />{" "}
            Keep record {side.toUpperCase()} (the other is merged into it)
          </label>
        ))}
      </fieldset>

      <div className="row-actions">
        {confirming === "merge" ? (
          <>
            <button
              className="button button-danger"
              type="button"
              disabled={busy}
              onClick={() => onMerge(survivorId, mergeValues(texts))}
            >
              Confirm merge
            </button>
            <button className="button button-secondary" type="button" onClick={() => setConfirming(null)}>
              Keep editing
            </button>
          </>
        ) : confirming === "distinct" ? (
          <>
            <button className="button button-danger" type="button" disabled={busy} onClick={onNotDuplicate}>
              Confirm not a duplicate
            </button>
            <button className="button button-secondary" type="button" onClick={() => setConfirming(null)}>
              Keep editing
            </button>
          </>
        ) : (
          <>
            <button className="button" type="button" disabled={busy} onClick={() => setConfirming("merge")}>
              Merge
            </button>
            <button
              className="button button-secondary"
              type="button"
              disabled={busy}
              onClick={() => setConfirming("distinct")}
            >
              Not a duplicate
            </button>
            <button className="button button-secondary" type="button" onClick={onClose}>
              Close
            </button>
          </>
        )}
      </div>
    </div>
  );
}
