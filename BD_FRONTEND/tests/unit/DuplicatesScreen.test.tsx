/**
 * Component tests for the duplicate review screen (task M2-B5).
 *
 * Needed so the list, the comparison, the merge and "not a duplicate" flows (each with a confirm
 * step) and the display of server refusals cannot regress unnoticed. The generated API client is
 * faked, so no request is sent, and every record below is synthetic. Permissions stay on the
 * server: the buttons are always shown and a 403 is only displayed.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DuplicatesScreen from "@/components/quality/DuplicatesScreen";

const { listMock, mergeMock, distinctMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  mergeMock: vi.fn(),
  distinctMock: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({
  listDuplicatesDuplicatesGet: listMock,
  mergeDuplicateDuplicatesCandidateIdMergePost: mergeMock,
  markNotDuplicateDuplicatesCandidateIdNotDuplicatePost: distinctMock,
}));

function card(id: string, fields: Record<string, string | null>, emails: string[]) {
  return {
    id,
    fields,
    emails,
    company_name: "Acme",
    owner_id: null,
    updated_at: "2026-11-26T10:00:00Z",
  };
}

function pair(overrides: Record<string, unknown> = {}) {
  return {
    id: "pair-1",
    reason: "name_and_company_domain",
    status: "open",
    created_at: "2026-11-26T10:00:00Z",
    decided_at: null,
    person_a: card(
      "person-a",
      { first_name: "Jane", last_name: "Doe", title: "Engineer" },
      ["old@acme.example"],
    ),
    person_b: card(
      "person-b",
      { first_name: "Jane", last_name: "Doe", title: "CTO" },
      ["new@acme.example"],
    ),
    suggested: { first_name: "a", last_name: "a", title: "b" },
    ...overrides,
  };
}

function listAnswer(items: unknown[], total = items.length) {
  return { data: { items, total, limit: 25, offset: 0 }, response: { status: 200 } };
}

function failure(status: number, error: unknown = {}) {
  return { error, response: { status } };
}

beforeEach(() => {
  vi.resetAllMocks();
  listMock.mockResolvedValue(listAnswer([pair()]));
});

/** Renders the screen, waits for the pair and opens its comparison. */
async function renderAndOpen() {
  const user = userEvent.setup();
  render(<DuplicatesScreen />);
  await screen.findByText(/Jane Doe · old@acme.example/);
  await user.click(screen.getByRole("button", { name: /Review Jane Doe/ }));
  return user;
}

describe("list", () => {
  it("loads the open pairs and shows both people", async () => {
    render(<DuplicatesScreen />);

    expect(await screen.findByText(/Jane Doe · old@acme.example/)).toBeInTheDocument();
    expect(screen.getByText(/Jane Doe · new@acme.example/)).toBeInTheDocument();
    expect(listMock).toHaveBeenCalledWith({ query: { status: "open", limit: 25, offset: 0 } });
  });

  it("choosing the other filter asks the server again with that status", async () => {
    const user = userEvent.setup();
    render(<DuplicatesScreen />);
    await screen.findByText(/old@acme.example/);

    await user.selectOptions(screen.getByLabelText("Show"), "not_duplicate");

    await waitFor(() =>
      expect(listMock).toHaveBeenLastCalledWith({
        query: { status: "not_duplicate", limit: 25, offset: 0 },
      }),
    );
  });

  it("an empty answer says no pairs match", async () => {
    listMock.mockResolvedValue(listAnswer([]));
    render(<DuplicatesScreen />);

    expect(await screen.findByText("No pairs match this filter.")).toBeInTheDocument();
  });

  it("a failed load shows the server's refusal and no list", async () => {
    listMock.mockResolvedValue(failure(403));
    render(<DuplicatesScreen />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Not permitted");
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("a decided pair has no Review button", async () => {
    listMock.mockResolvedValue(listAnswer([pair({ status: "not_duplicate" })]));
    render(<DuplicatesScreen />);
    await screen.findByText(/old@acme.example/);

    expect(screen.queryByRole("button", { name: /Review/ })).toBeNull();
  });
});

describe("compare and merge", () => {
  it("starts every field with the value the server pre-selected", async () => {
    await renderAndOpen();

    expect(screen.getByLabelText("Value to keep for Job title")).toHaveValue("CTO");
    expect(screen.getByLabelText("Value to keep for First name")).toHaveValue("Jane");
    expect(screen.getByText("All addresses of both records are kept.")).toBeInTheDocument();
  });

  it("choosing the other record fills that value", async () => {
    const user = await renderAndOpen();

    await user.click(screen.getByLabelText("Use record A Job title"));

    expect(screen.getByLabelText("Value to keep for Job title")).toHaveValue("Engineer");
  });

  it("merge needs a second click, then sends the survivor and the chosen values", async () => {
    mergeMock.mockResolvedValue({
      data: { survivor_id: "person-a", absorbed_person_id: "person-b", merge_record_id: "m1" },
      response: { status: 200 },
    });
    const user = await renderAndOpen();

    await user.click(screen.getByRole("button", { name: "Merge" }));
    expect(mergeMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm merge" }));

    await waitFor(() =>
      expect(mergeMock).toHaveBeenCalledWith({
        path: { candidate_id: "pair-1" },
        body: {
          survivor_id: "person-a",
          values: { first_name: "Jane", last_name: "Doe", title: "CTO" },
        },
      }),
    );
    expect(await screen.findByText("Merged. The two records are now one lead.")).toBeInTheDocument();
    expect(listMock.mock.calls.length).toBeGreaterThan(1);
  });

  it("keeping record B sends its id as the survivor", async () => {
    mergeMock.mockResolvedValue({
      data: { survivor_id: "person-b", absorbed_person_id: "person-a", merge_record_id: "m1" },
      response: { status: 200 },
    });
    const user = await renderAndOpen();

    await user.click(screen.getByLabelText(/Keep record B/));
    await user.click(screen.getByRole("button", { name: "Merge" }));
    await user.click(screen.getByRole("button", { name: "Confirm merge" }));

    await waitFor(() =>
      expect(mergeMock).toHaveBeenCalledWith(
        expect.objectContaining({ body: expect.objectContaining({ survivor_id: "person-b" }) }),
      ),
    );
  });

  it("'Keep editing' cancels the confirmation without calling the server", async () => {
    const user = await renderAndOpen();

    await user.click(screen.getByRole("button", { name: "Merge" }));
    await user.click(screen.getByRole("button", { name: "Keep editing" }));

    expect(mergeMock).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Merge" })).toBeInTheDocument();
  });

  it("409: shows the server's text and refreshes the list", async () => {
    mergeMock.mockResolvedValue(failure(409, { detail: "This pair was already decided." }));
    const user = await renderAndOpen();
    const callsBefore = listMock.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "Merge" }));
    await user.click(screen.getByRole("button", { name: "Confirm merge" }));

    expect(await screen.findByText("This pair was already decided.")).toBeInTheDocument();
    await waitFor(() => expect(listMock.mock.calls.length).toBeGreaterThan(callsBefore));
  });

  it("403: the refusal is only displayed; the button was shown to this user anyway", async () => {
    mergeMock.mockResolvedValue(failure(403));
    const user = await renderAndOpen();

    await user.click(screen.getByRole("button", { name: "Merge" }));
    await user.click(screen.getByRole("button", { name: "Confirm merge" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Not permitted");
    expect(alert.textContent).not.toMatch(/rep|manager|admin/i);
  });
});

describe("not a duplicate", () => {
  it("needs a second click, then marks the pair and refreshes", async () => {
    distinctMock.mockResolvedValue({
      data: pair({ status: "not_duplicate" }),
      response: { status: 200 },
    });
    const user = await renderAndOpen();

    await user.click(screen.getByRole("button", { name: "Not a duplicate" }));
    expect(distinctMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm not a duplicate" }));

    await waitFor(() =>
      expect(distinctMock).toHaveBeenCalledWith({ path: { candidate_id: "pair-1" } }),
    );
    expect(await screen.findByText(/will not be shown again/)).toBeInTheDocument();
  });
});
