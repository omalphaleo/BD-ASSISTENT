/**
 * Component tests for the quarantine screen (task M2-B2).
 *
 * Needed so the screen's behaviour cannot regress unnoticed: the list and its filters, editing,
 * release (including the clear message for the 503 "not available until M2-B4" answer), discard
 * with a confirm step, and that permissions are left to the server (every button is shown; a 403
 * is only displayed). The generated API client is faked, so no request is sent, and every row
 * below is synthetic.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import QuarantineScreen from "@/components/quality/QuarantineScreen";

// Stand-ins created with vi.hoisted so the vi.mock factory below can use them.
const { listMock, fixMock, releaseMock, discardMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  fixMock: vi.fn(),
  releaseMock: vi.fn(),
  discardMock: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({
  listQuarantineQuarantineGet: listMock,
  fixQuarantineRecordQuarantineRecordIdPatch: fixMock,
  releaseQuarantineRecordQuarantineRecordIdReleasePost: releaseMock,
  discardQuarantineRecordQuarantineRecordIdDiscardPost: discardMock,
}));

/** A synthetic quarantine record; pass overrides for the fields a test cares about. */
function record(overrides: Record<string, unknown> = {}) {
  return {
    id: "rec-1",
    status: "open",
    issues: ["personal_email_only"],
    payload: { first_name: "Jane", email: "jane@gmail.example" },
    import_file_id: "file-1",
    filename: "leads.csv",
    row_number: 7,
    uploaded_by: "user-1",
    created_at: "2026-11-26T10:00:00Z",
    resolved_at: null,
    resolved_by: null,
    ...overrides,
  };
}

/** A successful list answer holding the given records. */
function listAnswer(items: unknown[], total = items.length) {
  return { data: { items, total, limit: 25, offset: 0 }, response: { status: 200 } };
}

/** An answer with no data, as the generated client returns for an error status. */
function failure(status: number, error: unknown = {}) {
  return { error, response: { status } };
}

beforeEach(() => {
  vi.resetAllMocks();
  listMock.mockResolvedValue(listAnswer([record()]));
});

/** Renders the screen and waits until the first row is shown. */
async function renderLoaded() {
  const user = userEvent.setup();
  render(<QuarantineScreen />);
  await screen.findByText("leads.csv");
  return user;
}

describe("list and filters", () => {
  it("loads the open rows on start and shows source, person and reason", async () => {
    await renderLoaded();

    expect(listMock).toHaveBeenCalledWith({
      query: { status: "open", issue: undefined, limit: 25, offset: 0 },
    });
    // The reason text is also a filter option, so look inside the table only.
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Only a personal email")).toBeInTheDocument();
    expect(table.getByText("jane@gmail.example")).toBeInTheDocument();
    expect(table.getByText(/Row 7/)).toBeInTheDocument();
  });

  it("choosing a reason asks the server again with that reason and the first page", async () => {
    const user = await renderLoaded();

    await user.selectOptions(screen.getByLabelText("Reason"), "generic_email_only");

    await waitFor(() =>
      expect(listMock).toHaveBeenLastCalledWith({
        query: { status: "open", issue: "generic_email_only", limit: 25, offset: 0 },
      }),
    );
  });

  it("choosing a status asks the server for that status", async () => {
    const user = await renderLoaded();

    await user.selectOptions(screen.getByLabelText("Status"), "all");

    await waitFor(() =>
      expect(listMock).toHaveBeenLastCalledWith({
        query: { status: "all", issue: undefined, limit: 25, offset: 0 },
      }),
    );
  });

  it("an empty answer shows 'No rows match these filters.'", async () => {
    listMock.mockResolvedValue(listAnswer([]));
    render(<QuarantineScreen />);

    expect(await screen.findByText("No rows match these filters.")).toBeInTheDocument();
  });

  it("a failed load shows an error and no table", async () => {
    listMock.mockResolvedValue(failure(403, { detail: "Not permitted" }));
    render(<QuarantineScreen />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Not permitted");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("a row with no reasons left is labelled 'Ready to release'", async () => {
    listMock.mockResolvedValue(listAnswer([record({ issues: [] })]));
    render(<QuarantineScreen />);

    expect(await screen.findByText("Ready to release")).toBeInTheDocument();
  });

  it("pages: 'Next' asks for the following page of 25", async () => {
    listMock.mockResolvedValue(listAnswer([record()], 40));
    const user = await renderLoaded();

    expect(screen.getByText("Showing 1–25 of 40")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(listMock).toHaveBeenLastCalledWith({
        query: { status: "open", issue: undefined, limit: 25, offset: 25 },
      }),
    );
  });

  it("released and discarded rows show no actions", async () => {
    listMock.mockResolvedValue(listAnswer([record({ status: "released" })]));
    render(<QuarantineScreen />);
    await screen.findByText("leads.csv");

    expect(screen.queryByRole("button", { name: /Release row/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Discard row/ })).toBeNull();
  });
});

describe("edit", () => {
  it("saves only the changed field and shows what is still to fix", async () => {
    fixMock.mockResolvedValue({
      data: record({ issues: [], payload: { first_name: "Jane", email: "jane@acme.example" } }),
      response: { status: 200 },
    });
    const user = await renderLoaded();

    await user.click(screen.getByRole("button", { name: "Edit row 7 of leads.csv" }));
    const emailInput = screen.getByLabelText("Email");
    await user.clear(emailInput);
    await user.type(emailInput, "jane@acme.example");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(fixMock).toHaveBeenCalledWith({
        path: { record_id: "rec-1" },
        body: { values: { email: "jane@acme.example" } },
      }),
    );
    expect(await screen.findByText(/ready to release/)).toBeInTheDocument();
    expect(listMock.mock.calls.length).toBeGreaterThan(1); // the list was refreshed
  });

  it("saving without a change shows a message and sends nothing", async () => {
    const user = await renderLoaded();

    await user.click(screen.getByRole("button", { name: "Edit row 7 of leads.csv" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("Nothing was changed.")).toBeInTheDocument();
    expect(fixMock).not.toHaveBeenCalled();
  });

  it("a 422 from the server is shown with its reason and the editor stays open", async () => {
    fixMock.mockResolvedValue(failure(422, { detail: "invalid field name" }));
    const user = await renderLoaded();

    await user.click(screen.getByRole("button", { name: "Edit row 7 of leads.csv" }));
    await user.type(screen.getByLabelText("Secondary email"), "x@acme.example");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText(/Some values are not acceptable: invalid field name/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeInTheDocument();
  });

  it("Cancel closes the editor without calling the server", async () => {
    const user = await renderLoaded();

    await user.click(screen.getByRole("button", { name: "Edit row 7 of leads.csv" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("form", { name: "Edit quarantined row" })).toBeNull();
    expect(fixMock).not.toHaveBeenCalled();
  });
});

describe("release", () => {
  it("503: shows the clear 'not available yet' message and leaves the row in the list", async () => {
    releaseMock.mockResolvedValue(failure(503, { detail: "Releasing valid rows is not available yet." }));
    const user = await renderLoaded();

    await user.click(screen.getByRole("button", { name: "Release row 7 of leads.csv" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("releasing it is not available yet");
    expect(alert.textContent).toContain("stays in quarantine");
    expect(releaseMock).toHaveBeenCalledWith({ path: { record_id: "rec-1" } });
    expect(screen.getByText("leads.csv")).toBeInTheDocument();
  });

  it("released: false lists what is still wrong and is not an error", async () => {
    releaseMock.mockResolvedValue({
      data: { released: false, outcome: null, record: record() },
      response: { status: 200 },
    });
    const user = await renderLoaded();

    await user.click(screen.getByRole("button", { name: "Release row 7 of leads.csv" }));

    const status = await screen.findByRole("status");
    expect(status.textContent).toContain("Not released yet. Still to fix: Only a personal email.");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("released: true says the row is now in the lead database and refreshes the list", async () => {
    releaseMock.mockResolvedValue({
      data: { released: true, outcome: "imported", record: record({ status: "released" }) },
      response: { status: 200 },
    });
    const user = await renderLoaded();

    await user.click(screen.getByRole("button", { name: "Release row 7 of leads.csv" }));

    expect(await screen.findByText(/now in the lead database/)).toBeInTheDocument();
    expect(listMock.mock.calls.length).toBeGreaterThan(1);
  });

  it("409: shows the server's text and refreshes the list", async () => {
    releaseMock.mockResolvedValue(failure(409, { detail: "This record was already released or discarded." }));
    const user = await renderLoaded();
    const callsBefore = listMock.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "Release row 7 of leads.csv" }));

    expect(await screen.findByText("This record was already released or discarded.")).toBeInTheDocument();
    await waitFor(() => expect(listMock.mock.calls.length).toBeGreaterThan(callsBefore));
  });
});

describe("discard", () => {
  it("needs a second click to confirm, then discards and refreshes", async () => {
    discardMock.mockResolvedValue({ data: record({ status: "discarded" }), response: { status: 200 } });
    const user = await renderLoaded();

    await user.click(screen.getByRole("button", { name: "Discard row 7 of leads.csv" }));
    expect(discardMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm discard row 7 of leads.csv" }));

    await waitFor(() => expect(discardMock).toHaveBeenCalledWith({ path: { record_id: "rec-1" } }));
    expect(await screen.findByText("Row discarded.")).toBeInTheDocument();
  });

  it("'Keep' cancels the confirmation without calling the server", async () => {
    const user = await renderLoaded();

    await user.click(screen.getByRole("button", { name: "Discard row 7 of leads.csv" }));
    await user.click(screen.getByRole("button", { name: "Keep" }));

    expect(discardMock).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Discard row 7 of leads.csv" })).toBeInTheDocument();
  });

  it("403: the server's refusal is only displayed; the button was shown to this user anyway", async () => {
    discardMock.mockResolvedValue(failure(403, { detail: "Not permitted" }));
    const user = await renderLoaded();

    // The screen never hides Discard based on a role: it always offers it and shows the answer.
    await user.click(screen.getByRole("button", { name: "Discard row 7 of leads.csv" }));
    await user.click(screen.getByRole("button", { name: "Confirm discard row 7 of leads.csv" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Not permitted");
    expect(within(alert).queryByText(/rep|manager|admin/i)).toBeNull();
  });
});
