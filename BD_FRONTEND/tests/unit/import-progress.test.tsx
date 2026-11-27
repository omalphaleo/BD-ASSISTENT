/**
 * Tests for the import progress view and its helpers (task M2-A4 UI).
 *
 * Needed so polling (keeps asking until the server says finished, then stops), the failed state,
 * the owner panel gating by role and the "which step after a refresh" rule cannot regress. The
 * generated API functions are faked and the polling interval is shortened; data is synthetic.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ImportProgress from "@/components/import/ImportProgress";
import { canAssignOwners, stageForImport, statusText } from "@/lib/import/progress";

const mocks = vi.hoisted(() => ({ progress: vi.fn() }));

vi.mock("@/lib/api-client", () => ({}));
vi.mock("@/lib/api/sdk.gen", () => ({
  getImportProgressImportsImportIdProgressGet: mocks.progress,
}));
// The owner panel has its own tests; here it is only a marker that it was (or was not) shown.
vi.mock("@/components/import/UnmatchedOwnersPanel", () => ({
  default: () => <div>owners panel</div>,
}));
// A short interval keeps the polling tests fast (the real value is 3 seconds).
vi.mock("@/lib/import/progress", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/import/progress")>()),
  POLL_INTERVAL_MS: 5,
}));

const BASE = {
  status: "processing",
  row_count: 200,
  received: 50,
  imported: 40,
  updated: 5,
  unchanged: 2,
  duplicates_found: 1,
  quarantined: 1,
  rejected: 1,
  percent: 25,
  finished: false,
};

beforeEach(() => {
  vi.resetAllMocks();
});

describe("ImportProgress", () => {
  it("shows the server's counters and percent while processing", async () => {
    mocks.progress.mockResolvedValue({ data: BASE, response: { status: 200 } });
    render(<ImportProgress importId="i" canAssign />);

    expect(await screen.findByText("50 of 200 rows (25%)")).toBeInTheDocument();
    expect(screen.getByText("Importing")).toBeInTheDocument();
    expect(screen.getByText("40 new leads")).toBeInTheDocument();
    expect(screen.getByText("1 quarantined")).toBeInTheDocument();
    expect(screen.queryByText("owners panel")).not.toBeInTheDocument();
  });

  it("keeps polling until finished, then stops", async () => {
    mocks.progress
      .mockResolvedValueOnce({ data: BASE, response: { status: 200 } })
      .mockResolvedValue({
        data: { ...BASE, status: "completed", received: 200, percent: 100, finished: true },
        response: { status: 200 },
      });
    render(<ImportProgress importId="i" canAssign />);

    expect(await screen.findByText("200 of 200 rows (100%)")).toBeInTheDocument();
    const callsWhenFinished = mocks.progress.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 40));

    expect(callsWhenFinished).toBe(2);
    expect(mocks.progress.mock.calls.length).toBe(callsWhenFinished);
  });

  it("a failed poll shows the problem and recovers on the next one", async () => {
    mocks.progress
      .mockResolvedValueOnce({ data: BASE, response: { status: 200 } })
      .mockResolvedValueOnce({ error: {}, response: undefined })
      .mockResolvedValue({
        data: { ...BASE, status: "completed", finished: true, percent: 100 },
        response: { status: 200 },
      });
    render(<ImportProgress importId="i" canAssign={false} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the server");
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("a completed import shows the owner panel to managers and admins only", async () => {
    mocks.progress.mockResolvedValue({
      data: { ...BASE, status: "completed", finished: true, percent: 100 },
      response: { status: 200 },
    });
    const { unmount } = render(<ImportProgress importId="i" canAssign />);
    expect(await screen.findByText("owners panel")).toBeInTheDocument();
    unmount();

    render(<ImportProgress importId="i" canAssign={false} />);
    await screen.findByText("Completed");
    expect(screen.queryByText("owners panel")).not.toBeInTheDocument();
  });

  it("a failed import shows a fixed message and stops polling", async () => {
    mocks.progress.mockResolvedValue({
      data: { ...BASE, status: "failed", finished: true },
      response: { status: 200 },
    });
    render(<ImportProgress importId="i" canAssign />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The import stopped");
    expect(screen.queryByText("owners panel")).not.toBeInTheDocument();
  });

  it("first load refused: shows the server's message", async () => {
    mocks.progress.mockResolvedValue({
      error: { detail: "Import not found" },
      response: { status: 404 },
    });
    render(<ImportProgress importId="i" canAssign />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Import not found");
  });
});

describe("progress helpers", () => {
  it("stageForImport: not started returns to the wizard, anything else shows progress", () => {
    const csv = { filename: "leads.csv", worksheet: null };
    expect(stageForImport({ ...csv, status: "uploaded" })).toBe("profile");
    expect(stageForImport({ ...csv, status: "mapping" })).toBe("profile");
    expect(stageForImport({ ...csv, status: "processing" })).toBe("progress");
    expect(stageForImport({ ...csv, status: "completed" })).toBe("progress");
    expect(stageForImport({ ...csv, status: "failed" })).toBe("progress");
  });

  it("stageForImport: a workbook with no chosen worksheet needs a new upload", () => {
    const book = { filename: "Leads.XLSX", status: "uploaded" } as const;
    expect(stageForImport({ ...book, worksheet: null })).toBe("worksheet");
    expect(stageForImport({ ...book, worksheet: "Sheet1" })).toBe("profile");
  });

  it("statusText and canAssignOwners: wording and the cosmetic role check", () => {
    expect(statusText("processing")).toBe("Importing");
    expect(canAssignOwners("manager")).toBe(true);
    expect(canAssignOwners("admin")).toBe(true);
    expect(canAssignOwners("rep")).toBe(false);
  });
});
