/**
 * Unit tests for the quarantine display helpers (task M2-B2).
 *
 * Needed so the wording of reason codes and error messages, and the "send only what changed"
 * rule of the editor, cannot regress unnoticed. The helpers are pure functions, so no API or
 * rendering is involved and all data below is synthetic.
 */
import { describe, expect, it } from "vitest";

import {
  ISSUE_LABELS,
  ISSUE_OPTIONS,
  MESSAGE_RELEASE_UNAVAILABLE,
  STATUS_OPTIONS,
  changedValues,
  describeFailure,
  describeReleaseResult,
  displayValue,
  issueLabel,
} from "@/lib/quality/quarantine";

describe("issueLabel", () => {
  it("returns readable text for every known reason code", () => {
    for (const [code, label] of Object.entries(ISSUE_LABELS)) {
      expect(issueLabel(code)).toBe(label);
    }
    expect(issueLabel("personal_email_only")).toBe("Only a personal email");
  });

  it("returns an unknown code unchanged, so a new server reason is still shown", () => {
    expect(issueLabel("some_future_rule")).toBe("some_future_rule");
  });
});

describe("filter options", () => {
  it("status filter starts with Open and offers all four server values", () => {
    expect(STATUS_OPTIONS.map((option) => option.value)).toEqual([
      "open",
      "released",
      "discarded",
      "all",
    ]);
  });

  it("reason filter starts with 'Any reason' and lists every reason code", () => {
    expect(ISSUE_OPTIONS[0]).toEqual({ value: "", label: "Any reason" });
    expect(ISSUE_OPTIONS.slice(1).map((option) => option.value)).toEqual(Object.keys(ISSUE_LABELS));
  });
});

describe("displayValue", () => {
  it("shows null and missing values as empty text and others as text", () => {
    expect(displayValue(null)).toBe("");
    expect(displayValue(undefined)).toBe("");
    expect(displayValue("Jane")).toBe("Jane");
    expect(displayValue(42)).toBe("42");
    expect(displayValue(false)).toBe("false");
  });
});

describe("changedValues", () => {
  const original = { first_name: "Jane", email: "jane@gmail.com", phone: 5551234 };

  it("returns only the fields whose text changed", () => {
    expect(
      changedValues(original, { first_name: "Jane", email: "jane@acme.com", phone: "5551234" }),
    ).toEqual({ email: "jane@acme.com" });
  });

  it("ignores surrounding spaces, so an untouched field is not sent", () => {
    expect(changedValues(original, { first_name: " Jane ", email: "jane@gmail.com" })).toEqual({});
  });

  it("keeps a cleared field as blank text, because the server clears blank values", () => {
    expect(changedValues(original, { first_name: "" })).toEqual({ first_name: "" });
  });

  it("treats a field the row never had, left blank, as unchanged", () => {
    expect(changedValues(original, { secondary_email: "" })).toEqual({});
    expect(changedValues(original, { secondary_email: "j@acme.com" })).toEqual({
      secondary_email: "j@acme.com",
    });
  });
});

describe("describeFailure", () => {
  it("503 on release: says releasing is not available yet and that nothing changed", () => {
    const text = describeFailure("release", 503);
    expect(text).toBe(MESSAGE_RELEASE_UNAVAILABLE);
    expect(text).toContain("not available yet");
    expect(text).toContain("stays in quarantine");
  });

  it("503 on another action: a generic message, not the release text", () => {
    expect(describeFailure("save", 503)).toBe("Something went wrong. Please try again.");
  });

  it("403: a 'not permitted' message that does not name a role or capability", () => {
    expect(describeFailure("discard", 403)).toBe(
      "Not permitted: the server did not allow this action for your account.",
    );
  });

  it("404: says the record no longer exists", () => {
    expect(describeFailure("release", 404)).toContain("no longer exists");
  });

  it("409: uses the server's fixed text, or a default when there is none", () => {
    expect(describeFailure("save", 409, { detail: "This record was already released or discarded." })).toBe(
      "This record was already released or discarded.",
    );
    expect(describeFailure("save", 409)).toBe("This record was already released or discarded.");
  });

  it("422: includes the server's reason, in its string or list form", () => {
    expect(describeFailure("save", 422, { detail: "invalid field name" })).toBe(
      "Some values are not acceptable: invalid field name",
    );
    expect(describeFailure("save", 422, { detail: [{ msg: "Too short." }] })).toBe(
      "Some values are not acceptable: Too short.",
    );
    expect(describeFailure("save", 422)).toBe("Something went wrong. Please try again.");
  });

  it("no answer (network failure): says the server cannot be reached", () => {
    expect(describeFailure("load", undefined)).toBe("Cannot reach the server. Please try again later.");
  });
});

describe("describeReleaseResult", () => {
  it("released: says the row is now in the lead database", () => {
    expect(describeReleaseResult(true, [])).toContain("now in the lead database");
  });

  it("not released with reasons: lists them in plain words", () => {
    expect(describeReleaseResult(false, ["personal_email_only", "missing_first_name"])).toBe(
      "Not released yet. Still to fix: Only a personal email; First name is missing.",
    );
  });

  it("not released with no reasons: says the import step refused it", () => {
    expect(describeReleaseResult(false, [])).toContain("import step still refused it");
  });
});
