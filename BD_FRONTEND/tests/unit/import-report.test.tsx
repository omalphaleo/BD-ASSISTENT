/**
 * Tests for the import report screen, the change list and their helpers (task M2-A5 UI).
 *
 * Needed so the report keeps showing exactly what the server returns (totals, reason-coded
 * failures), pages the change list, saves the CSV only from a real file answer, shows the
 * server's refusal (for example "not finished"), and never renders uploaded text as markup. The
 * generated API functions are faked; data is synthetic.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ImportChangesList from "@/components/import/ImportChangesList";
import ImportReport from "@/components/import/ImportReport";
import { pageCount, reasonText, saveCsvResult, valueText } from "@/lib/import/report";

const mocks = vi.hoisted(() => ({
  report: vi.fn(),
  changes: vi.fn(),
  failedRows: vi.fn(),
  changesCsv: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({}));
vi.mock("@/lib/api/sdk.gen", () => ({
  getImportReportImportsImportIdReportGet: mocks.report,
  getImportChangesImportsImportIdChangesGet: mocks.changes,
  downloadFailedRowsImportsImportIdDownloadFailedRowsCsvGet: mocks.failedRows,
  downloadChangesImportsImportIdDownloadChangesCsvGet: mocks.changesCsv,
}));

const REPORT = {
  status: "completed",
  filename: "leads.csv",
  row_count: 10,
  received: 10,
  imported: 5,
  updated: 2,
  unchanged: 1,
  duplicates_found: 0,
  quarantined: 1,
  rejected: 1,
  failure_reasons: [
    { code: "personal_email_only", count: 1 },
    { code: "ingest_error", count: 1 },
  ],
  changes_total: 2,
};

function changesPage(page: number, total: number) {
  return {
    total,
    page,
    page_size: 50,
    items: [
      {
        person_id: `p${page}`,
        name: `Lead on page ${page}`,
        email: "lead@example.com",
        changes: [{ field: "title", label: "Job title", old: null, new: "<b>CTO</b>" }],
      },
    ],
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
});

describe("report helpers", () => {
  it("words reason codes and empty values", () => {
    expect(reasonText("ingest_error")).toBe("Unexpected error while processing the row");
    expect(reasonText("personal_email_only")).toBe("personal email only");
    expect(valueText(null)).toBe("(empty)");
    expect(valueText("")).toBe("(empty)");
    expect(valueText(0)).toBe("0");
    expect(valueText(false)).toBe("false");
  });

  it("counts pages, with at least one", () => {
    expect(pageCount(0, 50)).toBe(1);
    expect(pageCount(50, 50)).toBe(1);
    expect(pageCount(51, 50)).toBe(2);
  });

  it("saves only a real file and otherwise returns the server's message", () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    expect(saveCsvResult({ data: new Blob(["a"]) }, "i1", "changes")).toBeNull();
    expect(click).toHaveBeenCalledOnce();

    const refused = saveCsvResult(
      { error: { detail: "The report is available when the import has finished." }, response: { status: 409 } as Response },
      "i1",
      "changes",
    );
    expect(refused).toBe("The report is available when the import has finished.");
    expect(click).toHaveBeenCalledOnce();
  });
});

describe("ImportReport", () => {
  it("shows the totals and the reason table from the server", async () => {
    mocks.report.mockResolvedValue({ data: REPORT, response: { status: 200 } });
    mocks.changes.mockResolvedValue({ data: changesPage(1, 2), response: { status: 200 } });
    render(<ImportReport importId="i1" />);

    expect(await screen.findByText("5 new leads")).toBeInTheDocument();
    expect(screen.getByText("10 rows received")).toBeInTheDocument();
    expect(screen.getByText("personal email only")).toBeInTheDocument();
    expect(screen.getByText("Unexpected error while processing the row")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("shows the server's message when the import has not finished", async () => {
    mocks.report.mockResolvedValue({
      error: { detail: "The report is available when the import has finished." },
      response: { status: 409 },
    });
    render(<ImportReport importId="i1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("has finished");
    expect(screen.getByRole("link", { name: "Back to the import" })).toBeInTheDocument();
  });

  it("warns that a failed import covers only the rows handled so far", async () => {
    mocks.report.mockResolvedValue({ data: { ...REPORT, status: "failed" }, response: { status: 200 } });
    mocks.changes.mockResolvedValue({ data: changesPage(1, 2), response: { status: 200 } });
    render(<ImportReport importId="i1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("only the rows handled so far");
  });

  it("downloads the failed rows through the client as a blob and shows a refusal", async () => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    mocks.report.mockResolvedValue({ data: REPORT, response: { status: 200 } });
    mocks.changes.mockResolvedValue({ data: changesPage(1, 2), response: { status: 200 } });
    mocks.failedRows.mockResolvedValueOnce({ data: new Blob(["x"]), response: { status: 200 } });
    mocks.changesCsv.mockResolvedValueOnce({ error: { detail: "Import not found" }, response: { status: 404 } });
    render(<ImportReport importId="i1" />);

    fireEvent.click(await screen.findByRole("button", { name: /failed and quarantined rows/ }));
    await waitFor(() => expect(mocks.failedRows).toHaveBeenCalled());
    expect(mocks.failedRows.mock.calls[0][0]).toMatchObject({
      path: { import_id: "i1" },
      parseAs: "blob",
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Download changes/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Import not found");
  });

  it("disables a download when there is nothing to download", async () => {
    mocks.report.mockResolvedValue({
      data: { ...REPORT, quarantined: 0, rejected: 0, failure_reasons: [], changes_total: 0 },
      response: { status: 200 },
    });
    mocks.changes.mockResolvedValue({ data: { total: 0, page: 1, page_size: 50, items: [] }, response: { status: 200 } });
    render(<ImportReport importId="i1" />);

    expect(await screen.findByText("No row was rejected or quarantined.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /failed and quarantined rows/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Download changes/ })).toBeDisabled();
  });
});

describe("ImportChangesList", () => {
  it("shows old and new values as plain text and pages with Next and Previous", async () => {
    mocks.changes.mockImplementation(({ query }: { query: { page: number } }) =>
      Promise.resolve({ data: changesPage(query.page, 51), response: { status: 200 } }),
    );
    const { container } = render(<ImportChangesList importId="i1" />);

    expect(await screen.findByText("Lead on page 1")).toBeInTheDocument();
    expect(screen.getByText(/Job title: \(empty\) → <b>CTO<\/b>/)).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull(); // uploaded text is never parsed as HTML
    expect(screen.getByText("Page 1 of 2 (51 leads)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Lead on page 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(mocks.changes.mock.calls.at(-1)?.[0]).toMatchObject({ query: { page: 2 } });
  });

  it("says so when no lead was changed", async () => {
    mocks.changes.mockResolvedValue({ data: { total: 0, page: 1, page_size: 50, items: [] }, response: { status: 200 } });
    render(<ImportChangesList importId="i1" />);

    expect(await screen.findByText("This import did not change any existing lead.")).toBeInTheDocument();
  });
});
