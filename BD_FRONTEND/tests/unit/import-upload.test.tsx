/**
 * Component tests for the import upload step (task M2-A1 UI).
 *
 * Needed so the duplicate warning (D-109), the worksheet picker and the fixed error messages
 * cannot regress. The generated API functions are faked, so no request is sent; the file is a
 * synthetic in-memory CSV.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UploadWizard from "@/components/import/UploadWizard";

// Stand-ins for the generated calls, created with vi.hoisted so the vi.mock factory can use them.
const { uploadMock, worksheetMock } = vi.hoisted(() => ({
  uploadMock: vi.fn(),
  worksheetMock: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({})); // the side-effect setup (base URL, CSRF) is not under test
vi.mock("@/lib/api/sdk.gen", () => ({
  uploadImportFileImportsUploadPost: uploadMock,
  chooseWorksheetImportsImportIdWorksheetPost: worksheetMock,
}));

const BASE_UPLOAD = {
  id: "11111111-1111-1111-1111-111111111111",
  filename: "leads.csv",
  status: "uploaded",
  worksheet: null,
  row_count: 3,
  size_bytes: 40,
  uploaded_by: null,
  created_at: "2026-11-26T10:00:00Z",
  worksheets: [],
  headers: ["Email"],
};

const DUPLICATE_BODY = {
  detail: "This file was already uploaded.",
  code: "duplicate_file",
  earlier_import_id: BASE_UPLOAD.id,
  earlier_uploaded_at: "2026-11-20T09:00:00Z",
  earlier_uploaded_by: "rep@example.test",
};

/** Picks a synthetic file and presses Upload. */
async function chooseFileAndUpload() {
  const user = userEvent.setup();
  render(<UploadWizard />);
  await user.upload(
    screen.getByLabelText("CSV or XLSX file"),
    new File(["Email\na@example.test"], "leads.csv"),
  );
  await user.click(screen.getByRole("button", { name: "Upload" }));
  return user;
}

beforeEach(() => vi.resetAllMocks());

describe("UploadWizard", () => {
  it("no file chosen: shows the 'choose a file' message and sends nothing", async () => {
    const user = userEvent.setup();
    render(<UploadWizard />);
    await user.click(screen.getByRole("button", { name: "Upload" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Choose a CSV or XLSX file first.");
    expect(uploadMock).not.toHaveBeenCalled();
  });

  it("CSV upload succeeds: shows the received file with its row count", async () => {
    uploadMock.mockResolvedValue({ data: BASE_UPLOAD, response: { status: 201 } });
    await chooseFileAndUpload();

    expect(await screen.findByText("File received")).toBeInTheDocument();
    expect(screen.getByText(/leads\.csv: 3 rows/)).toBeInTheDocument();
  });

  it("duplicate file: warns with earlier user; 'Import anyway' re-sends with allow_duplicate", async () => {
    uploadMock
      .mockResolvedValueOnce({ error: DUPLICATE_BODY, response: { status: 409 } })
      .mockResolvedValueOnce({ data: BASE_UPLOAD, response: { status: 201 } });
    const user = await chooseFileAndUpload();

    expect(await screen.findByText("This file was already uploaded")).toBeInTheDocument();
    expect(screen.getByText(/by rep@example\.test/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Import anyway" }));

    await waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(2));
    expect(uploadMock.mock.calls[0][0].body.allow_duplicate).toBe(false);
    expect(uploadMock.mock.calls[1][0].body.allow_duplicate).toBe(true);
    expect(await screen.findByText("File received")).toBeInTheDocument();
  });

  it("duplicate file, Cancel: returns to the empty form without a second upload", async () => {
    uploadMock.mockResolvedValue({ error: DUPLICATE_BODY, response: { status: 409 } });
    const user = await chooseFileAndUpload();
    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(screen.getByLabelText("CSV or XLSX file")).toBeInTheDocument();
    expect(uploadMock).toHaveBeenCalledTimes(1);
  });

  it("multi-sheet workbook: shows the picker and sends the chosen worksheet", async () => {
    uploadMock.mockResolvedValue({
      data: {
        ...BASE_UPLOAD,
        filename: "leads.xlsx",
        headers: null,
        worksheets: [
          { name: "Leads", row_count: 5, selectable: true },
          { name: "Empty", row_count: 0, selectable: false },
        ],
      },
      response: { status: 201 },
    });
    worksheetMock.mockResolvedValue({
      data: { ...BASE_UPLOAD, worksheet: "Leads", row_count: 5 },
      response: { status: 200 },
    });
    const user = await chooseFileAndUpload();

    expect(await screen.findByText("Choose a worksheet")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Use this worksheet" }));

    await waitFor(() => expect(worksheetMock).toHaveBeenCalled());
    expect(worksheetMock.mock.calls[0][0].body).toEqual({ worksheet: "Leads" });
    expect(await screen.findByText(/worksheet Leads: 5 rows/)).toBeInTheDocument();
  });

  it("refused file (415): shows the server's fixed message", async () => {
    uploadMock.mockResolvedValue({
      error: { detail: "Only CSV and XLSX files are accepted.", code: "unsupported_type" },
      response: { status: 415 },
    });
    await chooseFileAndUpload();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only CSV and XLSX files are accepted.",
    );
  });

  it("network failure (no response): shows the 'cannot reach the server' message", async () => {
    uploadMock.mockResolvedValue({ error: undefined, response: undefined });
    await chooseFileAndUpload();

    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the server.");
  });
});
