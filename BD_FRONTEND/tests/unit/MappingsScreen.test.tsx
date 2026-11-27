/**
 * Component tests for the mappings admin screen (task M2-B6).
 *
 * Needed so listing, searching, adding and editing of industry and state mappings, and the
 * display of the server's refusals, cannot regress unnoticed. The generated API client is faked,
 * so no request is sent, and every row below is synthetic. Permissions stay on the server: the
 * forms are always shown and a 403 or 409 is only displayed.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MappingsScreen from "@/components/admin/MappingsScreen";

const mocks = vi.hoisted(() => ({
  listIndustries: vi.fn(),
  createIndustry: vi.fn(),
  updateIndustry: vi.fn(),
  listStates: vi.fn(),
  createState: vi.fn(),
  updateState: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({
  listIndustryMappingsReferenceMappingsIndustriesGet: mocks.listIndustries,
  createIndustryMappingReferenceMappingsIndustriesPost: mocks.createIndustry,
  updateIndustryMappingReferenceMappingsIndustriesMappingIdPatch: mocks.updateIndustry,
  listStateMappingsReferenceMappingsStatesGet: mocks.listStates,
  createStateMappingReferenceMappingsStatesPost: mocks.createState,
  updateStateMappingReferenceMappingsStatesMappingIdPatch: mocks.updateState,
}));

const industry = {
  id: "i1",
  source_name: "software dev",
  standard_industry: "Information",
  naics_sector: "51",
  updated_at: "2026-11-26T10:00:00Z",
};
const state = {
  id: "s1",
  country: "United States",
  source_value: "calif.",
  standard_name: "California",
  abbreviation: "CA",
  updated_at: "2026-11-26T10:00:00Z",
};

function page(items: unknown[]) {
  return { data: { items, total: items.length, limit: 25, offset: 0 }, response: { status: 200 } };
}

function failure(status: number, error: unknown = {}) {
  return { error, response: { status } };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.listIndustries.mockResolvedValue(page([industry]));
  mocks.listStates.mockResolvedValue(page([state]));
});

describe("industries", () => {
  it("lists the mappings on start", async () => {
    render(<MappingsScreen />);

    expect(await screen.findByText("software dev")).toBeInTheDocument();
    expect(screen.getByText("Information")).toBeInTheDocument();
    expect(mocks.listIndustries).toHaveBeenCalledWith({
      query: { search: undefined, limit: 25, offset: 0 },
    });
  });

  it("searching asks the server with the text", async () => {
    const user = userEvent.setup();
    render(<MappingsScreen />);
    await screen.findByText("software dev");

    const form = screen.getByRole("form", { name: "Search industry mappings" });
    await user.type(within(form).getByLabelText("Search wording"), "soft");
    await user.click(within(form).getByRole("button", { name: "Search" }));

    await waitFor(() =>
      expect(mocks.listIndustries).toHaveBeenLastCalledWith({
        query: { search: "soft", limit: 25, offset: 0 },
      }),
    );
  });

  it("adding sends the typed values, blank sector as null, and refreshes", async () => {
    mocks.createIndustry.mockResolvedValue({ data: industry, response: { status: 201 } });
    const user = userEvent.setup();
    render(<MappingsScreen />);
    await screen.findByText("software dev");

    const form = screen.getByRole("form", { name: "Add industry mapping" });
    await user.type(within(form).getByLabelText("Wording in the file"), "Gadgets");
    await user.type(within(form).getByLabelText("Standard industry"), "Manufacturing");
    await user.click(within(form).getByRole("button", { name: "Add mapping" }));

    await waitFor(() =>
      expect(mocks.createIndustry).toHaveBeenCalledWith({
        body: { source_name: "Gadgets", standard_industry: "Manufacturing", naics_sector: null },
      }),
    );
    expect(await screen.findByText("Industry mapping added.")).toBeInTheDocument();
    expect(mocks.listIndustries.mock.calls.length).toBeGreaterThan(1);
  });

  it("409 on add shows the server's fixed message", async () => {
    mocks.createIndustry.mockResolvedValue(
      failure(409, { detail: "A mapping for this wording already exists." }),
    );
    const user = userEvent.setup();
    render(<MappingsScreen />);
    await screen.findByText("software dev");

    const form = screen.getByRole("form", { name: "Add industry mapping" });
    await user.type(within(form).getByLabelText("Wording in the file"), "x");
    await user.click(within(form).getByRole("button", { name: "Add mapping" }));

    expect((await screen.findByRole("alert")).textContent).toContain("already exists");
  });

  it("editing saves the changed values and shows a notice", async () => {
    mocks.updateIndustry.mockResolvedValue({ data: industry, response: { status: 200 } });
    const user = userEvent.setup();
    render(<MappingsScreen />);
    await screen.findByText("software dev");

    await user.click(screen.getByRole("button", { name: "Edit software dev" }));
    const table = within(screen.getByRole("table"));
    const standard = table.getByLabelText("Standard industry");
    await user.clear(standard);
    await user.type(standard, "Technology");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mocks.updateIndustry).toHaveBeenCalledWith({
        path: { mapping_id: "i1" },
        body: { source_name: "software dev", standard_industry: "Technology", naics_sector: "51" },
      }),
    );
    expect(await screen.findByText("Industry mapping saved.")).toBeInTheDocument();
  });

  it("a refused load is only displayed", async () => {
    mocks.listIndustries.mockResolvedValue(failure(403));
    render(<MappingsScreen />);

    expect((await screen.findByRole("alert")).textContent).toContain("Not permitted");
  });
});

describe("states", () => {
  it("the States tab lists state mappings", async () => {
    const user = userEvent.setup();
    render(<MappingsScreen />);
    await screen.findByText("software dev");

    await user.click(screen.getByRole("button", { name: "States" }));

    expect(await screen.findByText("calif.")).toBeInTheDocument();
    expect(screen.getByText("California")).toBeInTheDocument();
  });

  it("adding a state sends the country, wording, name and abbreviation", async () => {
    mocks.createState.mockResolvedValue({ data: state, response: { status: 201 } });
    const user = userEvent.setup();
    render(<MappingsScreen />);
    await user.click(await screen.findByRole("button", { name: "States" }));
    await screen.findByText("calif.");

    const form = screen.getByRole("form", { name: "Add state mapping" });
    await user.type(within(form).getByLabelText("Wording in the file"), "Cali");
    await user.type(within(form).getByLabelText("Standard name"), "California");
    await user.type(within(form).getByLabelText("Abbreviation (optional)"), "CA");
    await user.click(within(form).getByRole("button", { name: "Add mapping" }));

    await waitFor(() =>
      expect(mocks.createState).toHaveBeenCalledWith({
        body: {
          country: "United States",
          source_value: "Cali",
          standard_name: "California",
          abbreviation: "CA",
        },
      }),
    );
    expect(await screen.findByText("State mapping added.")).toBeInTheDocument();
  });

  it("a 404 when saving a state shows the message and refreshes the list", async () => {
    mocks.updateState.mockResolvedValue(failure(404));
    const user = userEvent.setup();
    render(<MappingsScreen />);
    await user.click(await screen.findByRole("button", { name: "States" }));
    await screen.findByText("calif.");
    const callsBefore = mocks.listStates.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "Edit calif." }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect((await screen.findByRole("alert")).textContent).toContain("no longer exists");
    await waitFor(() => expect(mocks.listStates.mock.calls.length).toBeGreaterThan(callsBefore));
  });
});
