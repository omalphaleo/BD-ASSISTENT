/**
 * Unit tests for the duplicate-review and mapping display helpers (tasks M2-B5 and M2-B6).
 *
 * Needed so the wording of failures and the rules for what the merge form sends cannot regress
 * unnoticed. The helpers are pure functions, so no API or rendering is involved and all data
 * below is synthetic.
 */
import { describe, expect, it } from "vitest";

import type { DuplicateCandidateResponse } from "@/lib/api-client";
import {
  describeReviewFailure,
  fieldLabel,
  mergeValues,
  personSummary,
  pickedSide,
  suggestedTexts,
} from "@/lib/quality/review";

function card(id: string, fields: Record<string, string | null>, emails: string[] = []) {
  return {
    id,
    fields,
    emails,
    company_name: null,
    owner_id: null,
    updated_at: "2026-11-26T10:00:00Z",
  };
}

const pair: DuplicateCandidateResponse = {
  id: "pair-1",
  reason: "name_and_company_domain",
  status: "open",
  created_at: "2026-11-26T10:00:00Z",
  decided_at: null,
  person_a: card("a", { first_name: "Jane", last_name: "Doe", title: "Engineer", city: "Austin" }, [
    "jane@acme.example",
  ]),
  person_b: card("b", { first_name: "Jane", last_name: "Doe", title: "CTO", city: null }),
  suggested: { first_name: "a", last_name: "a", title: "b", city: "a" },
};

describe("fieldLabel", () => {
  it("returns readable text for a known field and a tidied name for an unknown one", () => {
    expect(fieldLabel("title")).toBe("Job title");
    expect(fieldLabel("some_new_field")).toBe("some new field");
  });
});

describe("describeReviewFailure", () => {
  it("no answer: says the server cannot be reached", () => {
    expect(describeReviewFailure(undefined)).toBe("Cannot reach the server. Please try again later.");
  });

  it("403: a 'not permitted' message that names no role", () => {
    expect(describeReviewFailure(403)).toBe(
      "Not permitted: the server did not allow this action for your account.",
    );
  });

  it("404: says the item no longer exists", () => {
    expect(describeReviewFailure(404)).toContain("no longer exists");
  });

  it("409: uses the server's fixed text, or a default when there is none", () => {
    expect(describeReviewFailure(409, { detail: "This pair was already decided." })).toBe(
      "This pair was already decided.",
    );
    expect(describeReviewFailure(409)).toContain("already");
  });

  it("422: includes the server's reason", () => {
    expect(describeReviewFailure(422, { detail: "A required value must not be blank." })).toBe(
      "Some values are not acceptable: A required value must not be blank.",
    );
    expect(describeReviewFailure(422)).toBe("Something went wrong. Please try again.");
  });
});

describe("personSummary", () => {
  it("shows the name and the first address", () => {
    expect(personSummary(pair.person_a)).toBe("Jane Doe · jane@acme.example");
  });

  it("falls back to '(no name)' when the person has none", () => {
    expect(personSummary(card("x", {}))).toBe("(no name)");
  });
});

describe("merge form helpers", () => {
  it("suggestedTexts starts every field with the value of the side the server pre-selected", () => {
    expect(suggestedTexts(pair)).toEqual({
      first_name: "Jane",
      last_name: "Doe",
      title: "CTO",
      city: "Austin",
    });
  });

  it("pickedSide tells which record a text equals, or null once it was edited", () => {
    expect(pickedSide(pair, "title", "Engineer")).toBe("a");
    expect(pickedSide(pair, "title", "CTO")).toBe("b");
    expect(pickedSide(pair, "title", "Chief")).toBeNull();
  });

  it("mergeValues drops blank texts, because a blank must never erase data", () => {
    expect(mergeValues({ title: " CTO ", city: "  ", state: "" })).toEqual({ title: "CTO" });
  });
});
