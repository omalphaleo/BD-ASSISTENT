/**
 * Tests for natural-language search on the Leads screen (task M3-A6, plan section 9).
 *
 * Needed so the box's promises cannot regress unnoticed: the sentence is sent through the
 * generated client, interpreted filters only fill the draft (no search runs until the user presses
 * Apply), what the app could not use is shown, and an AI outage shows a plain message while normal
 * search keeps working. The generated client is faked, so no request is sent; the sentences and
 * leads are synthetic.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NlSearchBox from "@/components/search/NlSearchBox";
import SearchScreen from "@/components/search/SearchScreen";
import {
  MAX_NL_QUERY_LENGTH,
  describeNlFailure,
  describeNotices,
  interpretQuery,
  isInterpretable,
} from "@/lib/search/nl-search";

// Stand-ins created with vi.hoisted so the vi.mock factory below can use them.
const { searchMock, optionsMock, listSegmentsMock, interpretMock } = vi.hoisted(() => ({
  searchMock: vi.fn(),
  optionsMock: vi.fn(),
  listSegmentsMock: vi.fn(),
  interpretMock: vi.fn(),
}));

vi.mock("@/lib/api/sdk.gen", () => ({
  searchLeadsSearchLeadsPost: searchMock,
  getFilterOptionsSearchFilterOptionsGet: optionsMock,
  listSegmentsSegmentsGet: listSegmentsMock,
  createSegmentSegmentsPost: vi.fn(),
  updateSegmentSegmentsSegmentIdPatch: vi.fn(),
  deleteSegmentSegmentsSegmentIdDelete: vi.fn(),
  interpretNlQuerySearchNlInterpretPost: interpretMock,
}));

const SENTENCE = "CFOs at pharma companies in Karnataka";

/** A successful interpretation. */
function interpreted(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      filters: { titles: ["CFO"], industries: ["Pharma"] },
      dropped_fields: [],
      unrecognised_terms: [],
      ...overrides,
    },
    response: { status: 200 },
  };
}

/** An answer with no data, as the generated client returns for an error status. */
function failure(status: number, error: unknown = {}) {
  return { error, response: { status } };
}

beforeEach(() => {
  vi.resetAllMocks();
  searchMock.mockResolvedValue({
    data: { items: [], total: 0, limit: 50, offset: 0 },
    response: { status: 200 },
  });
  optionsMock.mockResolvedValue({
    data: {
      industries: ["Pharma"],
      countries: [],
      states: [],
      cities: [],
      funding_stages: [],
      technologies: [],
      size_bands: ["smb"],
      flags: ["qualified"],
      truncated: [],
    },
  });
  listSegmentsMock.mockResolvedValue({ data: { items: [] }, response: { status: 200 } });
});

describe("nl-search helpers", () => {
  it("accepts a non-blank sentence within the limit and nothing else", () => {
    expect(isInterpretable(SENTENCE)).toBe(true);
    expect(isInterpretable("   ")).toBe(false);
    expect(isInterpretable("")).toBe(false);
    expect(isInterpretable("x".repeat(MAX_NL_QUERY_LENGTH))).toBe(true);
    expect(isInterpretable("x".repeat(MAX_NL_QUERY_LENGTH + 1))).toBe(false);
  });

  it("words each failure in plain language and shows the server's own sentence for 502 and 503", () => {
    expect(describeNlFailure(undefined, {})).toMatch(/could not be reached/);
    expect(describeNlFailure(403, {})).toMatch(/permission/);
    expect(describeNlFailure(422, {})).toMatch(/too long/);
    expect(describeNlFailure(503, { detail: "AI search is unavailable right now." })).toBe(
      "AI search is unavailable right now.",
    );
    expect(describeNlFailure(503, { detail: { nested: true } })).toMatch(/unavailable/);
    expect(describeNlFailure(502, null)).toMatch(/unavailable/);
    expect(describeNlFailure(500, {})).toMatch(/failed/);
  });

  it("lists what was not understood and what was ignored, and nothing when all was used", () => {
    expect(describeNotices([], [])).toEqual([]);
    expect(describeNotices(["salary"], ["pharma-ish"])).toEqual([
      "Not understood: pharma-ish.",
      "Ignored (not a filter you can set this way): salary.",
    ]);
  });

  it("sends the trimmed sentence and returns the draft filters", async () => {
    interpretMock.mockResolvedValue(interpreted({ unrecognised_terms: ["xyz"] }));

    const outcome = await interpretQuery(`  ${SENTENCE}  `);

    expect(interpretMock).toHaveBeenCalledWith({ body: { query: SENTENCE } });
    expect(outcome).toEqual({
      ok: true,
      filters: { titles: ["CFO"], industries: ["Pharma"] },
      droppedFields: [],
      unrecognisedTerms: ["xyz"],
    });
  });

  it("turns an error answer into a message instead of throwing", async () => {
    interpretMock.mockResolvedValue(failure(503, { detail: "AI search is unavailable right now." }));

    const outcome = await interpretQuery(SENTENCE);

    expect(outcome).toEqual({ ok: false, message: "AI search is unavailable right now." });
  });
});

describe("NlSearchBox", () => {
  it("keeps Interpret disabled until there is a sentence", async () => {
    render(<NlSearchBox onInterpreted={vi.fn()} />);
    const button = screen.getByRole("button", { name: "Interpret" });

    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Describe who you are looking for/), SENTENCE);
    expect(button).toBeEnabled();
  });

  it("hands the interpreted filters to the screen and lists what was not used", async () => {
    interpretMock.mockResolvedValue(
      interpreted({ dropped_fields: ["salary"], unrecognised_terms: ["underwater"] }),
    );
    const onInterpreted = vi.fn();
    render(<NlSearchBox onInterpreted={onInterpreted} />);

    await userEvent.type(screen.getByLabelText(/Describe who you are looking for/), SENTENCE);
    await userEvent.click(screen.getByRole("button", { name: "Interpret" }));

    await waitFor(() =>
      expect(onInterpreted).toHaveBeenCalledWith({ titles: ["CFO"], industries: ["Pharma"] }),
    );
    expect(screen.getByText(/Check them, edit if needed, then press Apply filters/)).toBeInTheDocument();
    expect(screen.getByText("Not understood: underwater.")).toBeInTheDocument();
    expect(screen.getByText(/Ignored .*: salary\./)).toBeInTheDocument();
  });

  it("shows an alert and loads nothing when the AI is unavailable", async () => {
    interpretMock.mockResolvedValue(failure(503, { detail: "AI search is unavailable right now. You can still use the filters." }));
    const onInterpreted = vi.fn();
    render(<NlSearchBox onInterpreted={onInterpreted} />);

    await userEvent.type(screen.getByLabelText(/Describe who you are looking for/), SENTENCE);
    await userEvent.click(screen.getByRole("button", { name: "Interpret" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/unavailable/);
    expect(onInterpreted).not.toHaveBeenCalled();
  });

  it("shows hostile text from the server as text, not markup", async () => {
    interpretMock.mockResolvedValue(
      interpreted({ unrecognised_terms: ["<img src=x onerror=alert(1)>"] }),
    );
    render(<NlSearchBox onInterpreted={vi.fn()} />);

    await userEvent.type(screen.getByLabelText(/Describe who you are looking for/), SENTENCE);
    await userEvent.click(screen.getByRole("button", { name: "Interpret" }));

    expect(await screen.findByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });
});

describe("NL box on the Leads screen", () => {
  it("fills the draft only: no search runs until the user presses Apply filters", async () => {
    interpretMock.mockResolvedValue(interpreted());
    render(<SearchScreen />);
    await waitFor(() => expect(searchMock).toHaveBeenCalled());
    const callsBefore = searchMock.mock.calls.length;

    await userEvent.type(screen.getByLabelText(/Describe who you are looking for/), SENTENCE);
    await userEvent.click(screen.getByRole("button", { name: "Interpret" }));
    await screen.findByText(/Check them, edit if needed/);

    expect(searchMock.mock.calls.length).toBe(callsBefore);

    await userEvent.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() =>
      expect(searchMock).toHaveBeenLastCalledWith({
        body: expect.objectContaining({
          filters: expect.objectContaining({ titles: ["CFO"], industries: ["Pharma"] }),
        }),
      }),
    );
  });

  it("keeps normal search working when the AI is unavailable", async () => {
    interpretMock.mockResolvedValue(failure(503, { detail: "AI search is unavailable right now." }));
    render(<SearchScreen />);
    await waitFor(() => expect(searchMock).toHaveBeenCalled());

    await userEvent.type(screen.getByLabelText(/Describe who you are looking for/), SENTENCE);
    await userEvent.click(screen.getByRole("button", { name: "Interpret" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/unavailable/);

    const callsBefore = searchMock.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(searchMock.mock.calls.length).toBeGreaterThan(callsBefore));
  });
});
