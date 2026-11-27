/**
 * Component tests for the Leads search screen (task M3-A3).
 *
 * Needed so the screen's behaviour cannot regress unnoticed: loading, empty, error and 403
 * states, paging and sorting calls, the filter panel and chips, row rendering (badges, the exact
 * lead link, hostile text shown as text), selection, "select all matching" and the disabled
 * "Add to campaign" button. The generated API client is faked, so no request is sent, and every
 * lead below is synthetic.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SearchScreen from "@/components/search/SearchScreen";

// Stand-ins created with vi.hoisted so the vi.mock factory below can use them.
const { searchMock, optionsMock, listSegmentsMock } = vi.hoisted(() => ({
  searchMock: vi.fn(),
  optionsMock: vi.fn(),
  listSegmentsMock: vi.fn(),
}));

// The screen also mounts the segments panel (M3-A4); here it only needs to see an empty list.
// Segment behaviour is tested in search-segments.test.tsx.
vi.mock("@/lib/api/sdk.gen", () => ({
  searchLeadsSearchLeadsPost: searchMock,
  getFilterOptionsSearchFilterOptionsGet: optionsMock,
  listSegmentsSegmentsGet: listSegmentsMock,
  createSegmentSegmentsPost: vi.fn(),
  updateSegmentSegmentsSegmentIdPatch: vi.fn(),
  deleteSegmentSegmentsSegmentIdDelete: vi.fn(),
}));

/** A synthetic result row; pass overrides for the fields a test cares about. */
function row(id: string, overrides: Record<string, unknown> = {}) {
  return {
    person_id: id,
    first_name: `First${id}`,
    last_name: "Last",
    title: "CFO",
    seniority: null,
    city: "Pune",
    state: null,
    country: "India",
    company: { id: "c1", name: "Acme", industry: "Pharma", employee_count: 50, hq_city: null, hq_state: null, hq_country: null },
    primary_email: { address: `${id}@acme.example`, verification_status: "verified" },
    owner: null,
    last_contacted_at: null,
    flags: [],
    badges: [],
    ...overrides,
  };
}

/** A successful search answer holding the given rows. */
function answer(items: unknown[], total = items.length) {
  return { data: { items, total, limit: 50, offset: 0 }, response: { status: 200 } };
}

/** An answer with no data, as the generated client returns for an error status. */
function failure(status: number) {
  return { error: {}, response: { status } };
}

const OPTIONS = {
  industries: ["Pharma", "Banking"],
  countries: [],
  states: [],
  cities: [],
  funding_stages: [],
  technologies: [],
  size_bands: ["smb"],
  flags: ["qualified"],
  truncated: [],
};

beforeEach(() => {
  vi.resetAllMocks();
  optionsMock.mockResolvedValue({ data: OPTIONS, response: { status: 200 } });
  listSegmentsMock.mockResolvedValue({ data: { items: [] }, response: { status: 200 } });
});

describe("SearchScreen", () => {
  it("shows a loading note, then the leads with name links, badges and flags", async () => {
    searchMock.mockResolvedValue(
      answer([row("1", { badges: ["replied", "opted_out"], flags: ["qualified"] })]),
    );
    render(<SearchScreen />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    const link = await screen.findByRole("link", { name: "First1 Last" });
    expect(link).toHaveAttribute("href", "/leads/1");
    expect(screen.getByText("Replied")).toBeInTheDocument();
    expect(screen.getByText("Opted out")).toBeInTheDocument();
    // "Qualified" is also a label in the filter panel, so look only inside the results table.
    expect(within(screen.getByRole("table")).getByText("Qualified")).toBeInTheDocument();
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
  });

  it("renders a hostile name as plain text, not as HTML", async () => {
    searchMock.mockResolvedValue(answer([row("1", { first_name: "<img src=x onerror=alert(1)>" })]));
    const { container } = render(<SearchScreen />);
    expect(await screen.findByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows an empty message when nothing matches", async () => {
    searchMock.mockResolvedValue(answer([]));
    render(<SearchScreen />);
    expect(await screen.findByText("No leads match these filters.")).toBeInTheDocument();
  });

  it("shows the permission message for a 403 and retries on request", async () => {
    searchMock.mockResolvedValueOnce(failure(403)).mockResolvedValueOnce(answer([row("1")]));
    render(<SearchScreen />);
    expect(await screen.findByRole("alert")).toHaveTextContent("do not have permission");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("link", { name: "First1 Last" })).toBeInTheDocument();
  });

  it("sends the first search with no filters, the default order and 50 per page", async () => {
    searchMock.mockResolvedValue(answer([row("1")]));
    render(<SearchScreen />);
    await screen.findByRole("link", { name: "First1 Last" });
    expect(searchMock).toHaveBeenCalledWith({
      body: { filters: {}, sort: "name", direction: "asc", limit: 50, offset: 0 },
    });
  });

  it("clicking a sort header re-sorts, and a second click flips the direction", async () => {
    searchMock.mockResolvedValue(answer([row("1")]));
    render(<SearchScreen />);
    await screen.findByRole("link", { name: "First1 Last" });
    await userEvent.click(screen.getByRole("button", { name: "Company" }));
    await waitFor(() =>
      expect(searchMock).toHaveBeenLastCalledWith({
        body: expect.objectContaining({ sort: "company", direction: "asc" }),
      }),
    );
    // The header now carries an arrow ("Company ▲"); /Company/ alone would also match the
    // "Company size" filter section once the filter options have loaded.
    await userEvent.click(screen.getByRole("button", { name: /^Company [▲▼]$/ }));
    await waitFor(() =>
      expect(searchMock).toHaveBeenLastCalledWith({
        body: expect.objectContaining({ sort: "company", direction: "desc" }),
      }),
    );
  });

  it("Next asks for offset 50 and Previous goes back; both disable at the ends", async () => {
    searchMock.mockResolvedValue(answer([row("1")], 120));
    render(<SearchScreen />);
    await screen.findByRole("link", { name: "First1 Last" });
    expect(screen.getByText(/Page 1 of 3/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(searchMock).toHaveBeenLastCalledWith({ body: expect.objectContaining({ offset: 50 }) }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Previous" }));
    await waitFor(() =>
      expect(searchMock).toHaveBeenLastCalledWith({ body: expect.objectContaining({ offset: 0 }) }),
    );
  });

  it("ticking a filter does not search until Apply; Apply sends it and shows a removable chip", async () => {
    searchMock.mockResolvedValue(answer([row("1")]));
    render(<SearchScreen />);
    await screen.findByRole("link", { name: "First1 Last" });
    const callsBefore = searchMock.mock.calls.length;
    await userEvent.click(await screen.findByRole("checkbox", { name: "Pharma" }));
    expect(searchMock.mock.calls.length).toBe(callsBefore);

    await userEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() =>
      expect(searchMock).toHaveBeenLastCalledWith({
        body: expect.objectContaining({ filters: expect.objectContaining({ industries: ["Pharma"] }) }),
      }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Remove filter Industry: Pharma" }));
    await waitFor(() =>
      expect(searchMock).toHaveBeenLastCalledWith({
        body: expect.objectContaining({ filters: expect.objectContaining({ industries: [] }) }),
      }),
    );
  });

  it("a reversed revenue range shows a message and sends no search", async () => {
    searchMock.mockResolvedValue(answer([row("1")]));
    render(<SearchScreen />);
    await screen.findByRole("link", { name: "First1 Last" });
    const callsBefore = searchMock.mock.calls.length;
    await userEvent.type(screen.getByLabelText("Minimum revenue"), "900");
    await userEvent.type(screen.getByLabelText("Maximum revenue"), "100");
    await userEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("must not exceed");
    expect(searchMock.mock.calls.length).toBe(callsBefore);
  });

  it("selecting a page offers 'select all matching', which keeps the count and locks the rows", async () => {
    searchMock.mockResolvedValue(answer([row("1"), row("2")], 120));
    render(<SearchScreen />);
    await screen.findByRole("link", { name: "First1 Last" });
    expect(screen.getByRole("button", { name: "Add to campaign" })).toBeDisabled();

    await userEvent.click(screen.getByRole("checkbox", { name: "Select all leads on this page" }));
    expect(screen.getByRole("status")).toHaveTextContent("2 selected");
    await userEvent.click(screen.getByRole("button", { name: "Select all 120 matching" }));
    expect(screen.getByRole("status")).toHaveTextContent("120 selected");
    expect(screen.getByRole("checkbox", { name: "Select First1 Last" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add to campaign" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByRole("status")).toHaveTextContent("0 selected");
  });

  it("applying new filters clears the selection", async () => {
    searchMock.mockResolvedValue(answer([row("1"), row("2")], 2));
    render(<SearchScreen />);
    await screen.findByRole("link", { name: "First1 Last" });
    await userEvent.click(screen.getByRole("checkbox", { name: "Select First1 Last" }));
    expect(screen.getByRole("status")).toHaveTextContent("1 selected");

    await userEvent.click(await screen.findByRole("checkbox", { name: "Pharma" }));
    await userEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    const bar = await screen.findByRole("status");
    await waitFor(() => expect(within(bar).getByText(/0 selected/)).toBeInTheDocument());
  });
});
