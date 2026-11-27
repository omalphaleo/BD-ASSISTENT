/**
 * Component tests for the import page host, ImportRunner, and the upload hand-off (task M2-A4 UI).
 *
 * Needed so resume after a refresh picks the right screen from the import's status, the
 * "Leave without importing" link is shown only before the import starts, and a finished upload
 * moves to the import's own URL. Child steps and the generated client are faked.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ImportRunner from "@/components/import/ImportRunner";
import ImportWizard from "@/components/import/ImportWizard";

const mocks = vi.hoisted(() => ({ status: vi.fn(), push: vi.fn(), role: { value: "manager" } }));

vi.mock("@/lib/api-client", () => ({}));
vi.mock("@/lib/api/sdk.gen", () => ({ getImportStatusImportsImportIdGet: mocks.status }));
vi.mock("@/lib/auth-context", () => ({
  useCurrentUser: () => ({ role: mocks.role.value }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/components/import/ProfileStep", () => ({
  default: ({ onDone }: { onDone: () => void }) => <button onClick={onDone}>profile step</button>,
}));
vi.mock("@/components/import/MappingStep", () => ({
  default: ({ onDone }: { onDone: () => void }) => <button onClick={onDone}>mapping step</button>,
}));
vi.mock("@/components/import/PreviewStep", () => ({
  default: ({ onStarted }: { onStarted: () => void }) => (
    <button onClick={onStarted}>preview step</button>
  ),
}));
vi.mock("@/components/import/ImportProgress", () => ({
  default: ({ canAssign }: { canAssign: boolean }) => <div>progress view {String(canAssign)}</div>,
}));
vi.mock("@/components/import/UploadWizard", () => ({
  default: ({ onReady }: { onReady: (upload: { id: string }) => void }) => (
    <button onClick={() => onReady({ id: "new-import" })}>upload done</button>
  ),
}));

/** An import as the status call returns it. */
function importWith(status: string, extra: Record<string, unknown> = {}) {
  return { data: { id: "i", status, filename: "leads.csv", worksheet: null, ...extra }, response: { status: 200 } };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.role.value = "manager";
});

describe("ImportRunner", () => {
  it("an import not started yet reopens the wizard and offers to leave", async () => {
    mocks.status.mockResolvedValue(importWith("mapping"));
    render(<ImportRunner importId="i" />);

    expect(await screen.findByText("profile step")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Leave without importing" })).toHaveAttribute(
      "href",
      "/leads/import",
    );
  });

  it("moves through the steps and to progress once the import starts", async () => {
    mocks.status.mockResolvedValue(importWith("uploaded"));
    const user = userEvent.setup();
    render(<ImportRunner importId="i" />);

    await user.click(await screen.findByText("profile step"));
    await user.click(await screen.findByText("mapping step"));
    await user.click(await screen.findByText("preview step"));

    expect(screen.getByText("progress view true")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Leave without importing" })).not.toBeInTheDocument();
  });

  it.each(["processing", "completed", "failed"])("a %s import opens the progress view", async (status) => {
    mocks.status.mockResolvedValue(importWith(status));
    render(<ImportRunner importId="i" />);

    expect(await screen.findByText("progress view true")).toBeInTheDocument();
  });

  it("a rep gets the progress view without the owner assignment", async () => {
    mocks.role.value = "rep";
    mocks.status.mockResolvedValue(importWith("completed"));
    render(<ImportRunner importId="i" />);

    expect(await screen.findByText("progress view false")).toBeInTheDocument();
  });

  it("a workbook with no chosen worksheet asks for a new upload", async () => {
    mocks.status.mockResolvedValue(importWith("uploaded", { filename: "leads.xlsx" }));
    render(<ImportRunner importId="i" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Upload the file again");
    expect(screen.queryByText("profile step")).not.toBeInTheDocument();
  });

  it("an import that cannot be loaded shows the server's message and a way back", async () => {
    mocks.status.mockResolvedValue({ error: { detail: "Import not found" }, response: { status: 404 } });
    render(<ImportRunner importId="missing" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Import not found");
    expect(screen.getByRole("link", { name: "Back to import" })).toBeInTheDocument();
  });
});

describe("ImportWizard", () => {
  it("a finished upload opens the import's own page", async () => {
    const user = userEvent.setup();
    render(<ImportWizard />);

    await user.click(screen.getByText("upload done"));

    expect(mocks.push).toHaveBeenCalledWith("/leads/import/new-import");
  });
});
