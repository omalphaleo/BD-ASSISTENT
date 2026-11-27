/**
 * Tests for the CSV export on the Leads search page (task M3-A5, D-087).
 *
 * Needed so the button's behaviour cannot regress unnoticed: it exports the applied filters and
 * order (never only the ticked rows), hands the file to the browser, shows the server's message
 * when the export is refused, and is off when nothing matches. The generated API client is
 * faked, so no request is sent; the server's rules (permission, cap, audit, formula
 * neutralisation) are tested in the backend. Every lead is synthetic.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SearchScreen from "@/components/search/SearchScreen";
import {
  FALLBACK_FILE_NAME,
  describeExportFailure,
  fileNameFrom,
} from "@/lib/search/export";

// Stand-ins created with vi.hoisted so the vi.mock factory below can use them.
const { searchMock, optionsMock, exportMock } = vi.hoisted(() => ({
  searchMock: vi.fn(),
  optionsMock: vi.fn(),
  exportMock: vi.fn(),
}));

vi.mock("@/lib/api/sdk.gen", () => ({
  searchLeadsSearchLeadsPost: searchMock,
  getFilterOptionsSearchFilterOptionsGet: optionsMock,
  exportLeadsSearchLeadsExportCsvPost: exportMock,
  // The screen also mounts the segments panel; it only needs an empty list here.
  listSegmentsSegmentsGet: vi.fn().mockResolvedValue({ data: { items: [] }, response: { status: 200 } }),
  createSegmentSegmentsPost: vi.fn(),
  updateSegmentSegmentsSegmentIdPatch: vi.fn(),
  deleteSegmentSegmentsSegmentIdDelete: vi.fn(),
}));

/** One synthetic result row. */
function row(id: string) {
  return {
    person_id: id,
    first_name: `First${id}`,
    last_name: "Last",
    title: "CFO",
    seniority: null,
    city: null,
    state: null,
    country: null,
    company: null,
    primary_email: null,
    owner: null,
    last_contacted_at: null,
    flags: [],
    badges: [],
  };
}

/** A successful search answer holding the given rows and total. */
function answer(items: unknown[], total = items.length) {
  return { data: { items, total, limit: 50, offset: 0 }, response: { status: 200 } };
}

/** A successful export answer: a CSV blob with a Content-Disposition header. */
function csvAnswer() {
  return {
    data: new Blob(["first_name\r\nAda\r\n"], { type: "text/csv" }),
    response: new Response(null, {
      status: 200,
      headers: { "content-disposition": 'attachment; filename="leads-2026-11-28.csv"' },
    }),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  optionsMock.mockResolvedValue({ data: undefined, response: { status: 500 } });
  searchMock.mockResolvedValue(answer([row("1")], 1));
  URL.createObjectURL = vi.fn(() => "blob:test");
  URL.revokeObjectURL = vi.fn();
});

describe("export helpers", () => {
  it("reads the file name from Content-Disposition and falls back when it is missing", () => {
    expect(fileNameFrom('attachment; filename="leads-2026-11-28.csv"')).toBe("leads-2026-11-28.csv");
    expect(fileNameFrom(null)).toBe(FALLBACK_FILE_NAME);
    expect(fileNameFrom("attachment")).toBe(FALLBACK_FILE_NAME);
  });

  it("shows the server's sentence for a 422 and plain text for other failures", () => {
    expect(describeExportFailure(422, { detail: "5 leads match; narrow it." })).toBe(
      "5 leads match; narrow it.",
    );
    expect(describeExportFailure(422, { detail: [{ msg: "x" }] })).toMatch(/export failed/i);
    expect(describeExportFailure(403, {})).toMatch(/not allowed/i);
    expect(describeExportFailure(undefined, undefined)).toMatch(/cannot reach/i);
  });
});

describe("Export CSV button", () => {
  it("exports the applied filters and order and saves the file", async () => {
    exportMock.mockResolvedValue(csvAnswer());
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<SearchScreen />);

    await userEvent.click(await screen.findByRole("button", { name: "Export CSV" }));

    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    expect(exportMock).toHaveBeenCalledWith({
      body: { filters: {}, sort: "name", direction: "asc" },
      parseAs: "blob",
    });
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).toBeNull();
    click.mockRestore();
  });

  it("ignores ticked rows: the request carries filters and order only", async () => {
    exportMock.mockResolvedValue(csvAnswer());
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<SearchScreen />);
    await userEvent.click(await screen.findByRole("checkbox", { name: /select first1/i }));

    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));

    await waitFor(() => expect(exportMock).toHaveBeenCalledTimes(1));
    expect(Object.keys(exportMock.mock.calls[0][0].body).sort()).toEqual([
      "direction",
      "filters",
      "sort",
    ]);
  });

  it("shows the server's message when the export is refused and saves nothing", async () => {
    exportMock.mockResolvedValue({
      error: { detail: "60000 leads match; one export holds at most 50000. Narrow the filters." },
      response: new Response(null, { status: 422 }),
    });
    render(<SearchScreen />);

    await userEvent.click(await screen.findByRole("button", { name: "Export CSV" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/60000 leads match/);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("is disabled when no lead matches", async () => {
    searchMock.mockResolvedValue(answer([], 0));
    render(<SearchScreen />);

    expect(await screen.findByRole("button", { name: "Export CSV" })).toBeDisabled();
  });
});
