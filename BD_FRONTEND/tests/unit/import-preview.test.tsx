/**
 * Component tests for the preview and estimate step of the import wizard (task M2-A2 UI).
 *
 * Needed so cell warnings, the estimate numbers, blocking issues and the disabled "Start import"
 * (planned for M2-A3) cannot regress. The generated API functions are faked; data is synthetic.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PreviewStep from "@/components/import/PreviewStep";

const mocks = vi.hoisted(() => ({ preview: vi.fn(), estimate: vi.fn() }));

vi.mock("@/lib/api-client", () => ({}));
vi.mock("@/lib/api/sdk.gen", () => ({
  readPreviewImportsImportIdPreviewGet: mocks.preview,
  readEstimateImportsImportIdEstimateGet: mocks.estimate,
}));

const PREVIEW = {
  rows: [
    { row_number: 2, values: { email: "a@example.test", employees: null }, warnings: [{ field: "employees", code: "not_an_integer" }] },
  ],
};
const ESTIMATE = {
  rows_total: 120,
  rows_without_email: 3,
  rows_without_first_name: 5,
  warning_counts: { employees: 2 },
  unmapped_columns: [{ column_index: 4, source_header: "Notes" }],
  blocking_issues: [],
  can_start: true,
};

beforeEach(() => {
  vi.resetAllMocks();
  mocks.preview.mockResolvedValue({ data: PREVIEW, response: { status: 200 } });
  mocks.estimate.mockResolvedValue({ data: ESTIMATE, response: { status: 200 } });
});

describe("PreviewStep", () => {
  it("shows rows, a readable cell warning, the estimate and the unmapped columns", async () => {
    render(<PreviewStep importId="i" onBack={vi.fn()} />);

    expect(await screen.findByText("a@example.test")).toBeInTheDocument();
    expect(screen.getByText(/Not a whole number/)).toBeInTheDocument();
    expect(screen.getByText("120 rows in the file")).toBeInTheDocument();
    expect(screen.getByText("3 rows without an email")).toBeInTheDocument();
    expect(screen.getByText(/Not mapped \(kept in the raw rows\): Notes/)).toBeInTheDocument();
  });

  it("start import: always disabled with the M2-A3 explanation", async () => {
    render(<PreviewStep importId="i" onBack={vi.fn()} />);
    await screen.findByText("Preview and estimate");

    expect(screen.getByRole("button", { name: "Start import" })).toBeDisabled();
    expect(screen.getByText(/available in M2-A3/)).toBeInTheDocument();
  });

  it("blocking issue from the server: shown as readable text", async () => {
    mocks.estimate.mockResolvedValue({
      data: { ...ESTIMATE, can_start: false, blocking_issues: ["email_not_mapped"] },
      response: { status: 200 },
    });
    render(<PreviewStep importId="i" onBack={vi.fn()} />);

    expect(await screen.findByText(/No column is mapped to Email/)).toBeInTheDocument();
  });

  it("Back to mapping: calls onBack", async () => {
    const onBack = vi.fn();
    const user = userEvent.setup();
    render(<PreviewStep importId="i" onBack={onBack} />);
    await user.click(await screen.findByRole("button", { name: "Back to mapping" }));

    expect(onBack).toHaveBeenCalled();
  });

  it("preview refused: shows the server's fixed message", async () => {
    mocks.preview.mockResolvedValue({
      error: { detail: "Save the mapping first.", code: "mapping_not_saved" },
      response: { status: 409 },
    });
    render(<PreviewStep importId="i" onBack={vi.fn()} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Save the mapping first.");
  });
});
