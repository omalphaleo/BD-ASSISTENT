/**
 * Tests for saved segments on the Leads search page (task M3-A4, D-009, D-098).
 *
 * Needed so the panel's behaviour cannot regress unnoticed: the two lists, the owner-only
 * buttons, saving the applied filters, rename, share, delete with a confirmation, a segment whose
 * saved filters are unsupported, refused changes, and that applying a segment runs a normal
 * search from page 1 with the selection cleared. The generated API client is faked, so no request
 * is sent; every segment below is synthetic. The server, not these tests, owns the real
 * permission rules (they are tested in the backend).
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SearchScreen from "@/components/search/SearchScreen";
import SegmentPanel from "@/components/search/SegmentPanel";
import {
  MAX_SEGMENT_NAME_LENGTH,
  describeSegmentFailure,
  groupSegments,
  isSaveableName,
  ownerLabel,
} from "@/lib/search/segments";

// Stand-ins created with vi.hoisted so the vi.mock factory below can use them.
const { searchMock, optionsMock, listMock, createMock, updateMock, deleteMock } = vi.hoisted(
  () => ({
    searchMock: vi.fn(),
    optionsMock: vi.fn(),
    listMock: vi.fn(),
    createMock: vi.fn(),
    updateMock: vi.fn(),
    deleteMock: vi.fn(),
  }),
);

vi.mock("@/lib/api/sdk.gen", () => ({
  searchLeadsSearchLeadsPost: searchMock,
  getFilterOptionsSearchFilterOptionsGet: optionsMock,
  listSegmentsSegmentsGet: listMock,
  createSegmentSegmentsPost: createMock,
  updateSegmentSegmentsSegmentIdPatch: updateMock,
  deleteSegmentSegmentsSegmentIdDelete: deleteMock,
}));

/** A synthetic segment; pass overrides for the fields a test cares about. */
function segment(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    name: `Segment ${id}`,
    visibility: "private",
    owner: { id: "me", email: "me@example.com" },
    can_edit: true,
    filters_valid: true,
    filters: { titles: ["CFO"] },
    created_at: "2026-11-27T10:00:00Z",
    updated_at: "2026-11-27T10:00:00Z",
    ...overrides,
  };
}

const ok = (status = 200) => ({ response: { ok: true, status } });
const refused = (status: number) => ({ error: {}, response: { ok: false, status } });
const listOf = (...items: unknown[]) => ({ data: { items }, response: { ok: true, status: 200 } });

beforeEach(() => {
  vi.resetAllMocks();
  listMock.mockResolvedValue(listOf());
  optionsMock.mockResolvedValue({ data: { industries: [], countries: [], states: [], cities: [], funding_stages: [], technologies: [], size_bands: [], flags: [], truncated: [] }, response: { status: 200 } });
  searchMock.mockResolvedValue({ data: { items: [], total: 0, limit: 50, offset: 0 }, response: { status: 200 } });
});

describe("segment helpers", () => {
  it("groups by the server's can_edit answer and names a missing owner", () => {
    const mine = segment("1") as never;
    const theirs = segment("2", { can_edit: false, owner: null }) as never;

    const groups = groupSegments([mine, theirs]);

    expect(groups.editable).toEqual([mine]);
    expect(groups.sharedByOthers).toEqual([theirs]);
    expect(ownerLabel(theirs)).toBe("no owner");
    expect(ownerLabel(mine)).toBe("me@example.com");
  });

  it("accepts a trimmed name of 1 to 255 characters and nothing else", () => {
    expect(isSaveableName("  Pharma  ")).toBe(true);
    expect(isSaveableName("   ")).toBe(false);
    expect(isSaveableName("")).toBe(false);
    expect(isSaveableName("n".repeat(MAX_SEGMENT_NAME_LENGTH))).toBe(true);
    expect(isSaveableName("n".repeat(MAX_SEGMENT_NAME_LENGTH + 1))).toBe(false);
  });

  it("gives a fixed message per status and a generic one otherwise", () => {
    expect(describeSegmentFailure(403)).toMatch(/owner/);
    expect(describeSegmentFailure(404)).toMatch(/no longer exists/);
    expect(describeSegmentFailure(422)).toMatch(/not accepted/);
    expect(describeSegmentFailure(401)).toMatch(/Sign in/);
    expect(describeSegmentFailure(500)).toMatch(/Something went wrong/);
    expect(describeSegmentFailure(undefined)).toMatch(/Something went wrong/);
  });
});

describe("SegmentPanel", () => {
  it("lists own and colleagues' segments apart; colleagues' have Apply only and show the owner", async () => {
    listMock.mockResolvedValue(
      listOf(
        segment("1", { name: "My list" }),
        segment("2", { name: "Team list", visibility: "shared", can_edit: false, owner: { id: "x", email: "colleague@example.com" } }),
      ),
    );
    render(<SegmentPanel filters={{}} onApply={vi.fn()} />);

    expect(await screen.findByText("My list")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Your segments" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Shared by colleagues" })).toBeInTheDocument();
    expect(screen.getByText(/colleague@example.com/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rename segment My list" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply segment Team list" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Rename segment Team list" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete segment Team list" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Share with the team: Team list/ })).toBeNull();
  });

  it("shows a note when there are no segments", async () => {
    render(<SegmentPanel filters={{}} onApply={vi.fn()} />);

    expect(await screen.findByText("No saved segments yet.")).toBeInTheDocument();
  });

  it("saves the applied filters under a trimmed name, private by default, then clears the form", async () => {
    createMock.mockResolvedValue(ok(201));
    render(<SegmentPanel filters={{ titles: ["CFO"] }} onApply={vi.fn()} />);
    const save = await screen.findByRole("button", { name: "Save current filters" });
    expect(save).toBeDisabled(); // blank name

    await userEvent.type(screen.getByLabelText("Segment name"), "  Pharma CFOs ");
    listMock.mockResolvedValue(listOf(segment("9", { name: "Pharma CFOs" })));
    await userEvent.click(save);

    await waitFor(() =>
      expect(createMock).toHaveBeenCalledWith({
        body: { name: "Pharma CFOs", filters: { titles: ["CFO"] }, visibility: "private" },
      }),
    );
    expect(await screen.findByText("Pharma CFOs")).toBeInTheDocument(); // list reloaded
    expect(screen.getByLabelText("Segment name")).toHaveValue("");
  });

  it("saves as shared when the share box is ticked", async () => {
    createMock.mockResolvedValue(ok(201));
    render(<SegmentPanel filters={{}} onApply={vi.fn()} />);
    await userEvent.type(await screen.findByLabelText("Segment name"), "Team");
    await userEvent.click(screen.getByRole("checkbox", { name: "Share with the team" }));
    await userEvent.click(screen.getByRole("button", { name: "Save current filters" }));

    await waitFor(() =>
      expect(createMock).toHaveBeenCalledWith({
        body: expect.objectContaining({ name: "Team", visibility: "shared" }),
      }),
    );
  });

  it("renames through an inline box and sends the trimmed name", async () => {
    listMock.mockResolvedValue(listOf(segment("1", { name: "Old name" })));
    updateMock.mockResolvedValue(ok());
    render(<SegmentPanel filters={{}} onApply={vi.fn()} />);

    await userEvent.click(await screen.findByRole("button", { name: "Rename segment Old name" }));
    const box = screen.getByLabelText("New name for Old name");
    await userEvent.clear(box);
    await userEvent.type(box, " New name ");
    await userEvent.click(screen.getByRole("button", { name: "Save name" }));

    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith({ path: { segment_id: "1" }, body: { name: "New name" } }),
    );
  });

  it("shares a private segment and makes a shared one private again", async () => {
    listMock.mockResolvedValue(
      listOf(segment("1", { name: "Private one" }), segment("2", { name: "Shared one", visibility: "shared" })),
    );
    updateMock.mockResolvedValue(ok());
    render(<SegmentPanel filters={{}} onApply={vi.fn()} />);

    await userEvent.click(await screen.findByRole("button", { name: "Share with the team: Private one" }));
    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith({ path: { segment_id: "1" }, body: { visibility: "shared" } }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Make private: Shared one" }));
    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith({ path: { segment_id: "2" }, body: { visibility: "private" } }),
    );
  });

  it("deletes only after the confirmation, and 'Keep' cancels", async () => {
    listMock.mockResolvedValue(listOf(segment("1", { name: "Doomed" })));
    deleteMock.mockResolvedValue(ok(204));
    render(<SegmentPanel filters={{}} onApply={vi.fn()} />);

    await userEvent.click(await screen.findByRole("button", { name: "Delete segment Doomed" }));
    expect(deleteMock).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Keep" }));
    expect(deleteMock).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Delete segment Doomed" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm delete of Doomed" }));
    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith({ path: { segment_id: "1" } }));
  });

  it("a segment with unsupported saved filters is listed, cannot be applied, but can still be deleted", async () => {
    listMock.mockResolvedValue(listOf(segment("1", { name: "Stale", filters_valid: false, filters: null })));
    render(<SegmentPanel filters={{}} onApply={vi.fn()} />);

    expect(await screen.findByText(/no longer supported/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply segment Stale" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete segment Stale" })).toBeEnabled();
  });

  it("applying a segment hands its filters to the screen", async () => {
    const onApply = vi.fn();
    listMock.mockResolvedValue(listOf(segment("1", { name: "Mine", filters: { titles: ["CFO"], industries: ["Pharma"] } })));
    render(<SegmentPanel filters={{}} onApply={onApply} />);

    await userEvent.click(await screen.findByRole("button", { name: "Apply segment Mine" }));

    expect(onApply).toHaveBeenCalledWith({ titles: ["CFO"], industries: ["Pharma"] });
  });

  it("a refused change shows the fixed message and reloads the list", async () => {
    listMock.mockResolvedValue(listOf(segment("1", { name: "Mine" })));
    updateMock.mockResolvedValue(refused(403));
    render(<SegmentPanel filters={{}} onApply={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Share with the team: Mine" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Only the owner can change this segment.");
    expect(listMock.mock.calls.length).toBeGreaterThanOrEqual(2); // initial load plus the reload
  });

  it("a request that gets no answer shows the generic message instead of freezing", async () => {
    listMock.mockResolvedValue(listOf(segment("1", { name: "Mine" })));
    deleteMock.mockRejectedValue(new Error("network down"));
    render(<SegmentPanel filters={{}} onApply={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete segment Mine" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm delete of Mine" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong with segments");
    // The confirmation stays open and its button is usable again: the panel is not stuck busy.
    expect(screen.getByRole("button", { name: "Confirm delete of Mine" })).toBeEnabled();
  });

  it("shows a message when the list cannot be loaded", async () => {
    listMock.mockResolvedValue(refused(500));
    render(<SegmentPanel filters={{}} onApply={vi.fn()} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong with segments");
  });

  it("shows a hostile segment name as text, not as markup", async () => {
    listMock.mockResolvedValue(listOf(segment("1", { name: "<img src=x onerror=alert(1)>" })));
    const { container } = render(<SegmentPanel filters={{}} onApply={vi.fn()} />);

    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("SearchScreen with segments", () => {
  it("applying a segment searches with its filters from page 1 and clears the selection", async () => {
    const item = {
      person_id: "p1", first_name: "First1", last_name: "Last", title: "CFO", seniority: null,
      city: null, state: null, country: null, company: null, primary_email: null, owner: null,
      last_contacted_at: null, flags: [], badges: [],
    };
    searchMock.mockResolvedValue({ data: { items: [item], total: 1, limit: 50, offset: 0 }, response: { status: 200 } });
    listMock.mockResolvedValue(listOf(segment("1", { name: "Pharma CFOs", filters: { industries: ["Pharma"] } })));
    render(<SearchScreen />);
    await userEvent.click(await screen.findByRole("checkbox", { name: "Select First1 Last" }));
    expect(screen.getByRole("status")).toHaveTextContent("1 selected");

    await userEvent.click(screen.getByRole("button", { name: "Apply segment Pharma CFOs" }));

    await waitFor(() =>
      expect(searchMock).toHaveBeenLastCalledWith({
        body: expect.objectContaining({ filters: { industries: ["Pharma"] }, offset: 0 }),
      }),
    );
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("0 selected"));
  });
});
