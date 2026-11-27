/**
 * Component tests for the unmatched-owner assignment panel (task M2-A4 UI; D-075).
 *
 * Needed so the list of owner texts, the "no owner given" group, the assign call with its counts
 * (assigned and already-owned) and the server's error messages cannot regress. The generated API
 * functions are faked; owner names and users are synthetic.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UnmatchedOwnersPanel from "@/components/import/UnmatchedOwnersPanel";

const mocks = vi.hoisted(() => ({ users: vi.fn(), groups: vi.fn(), assign: vi.fn() }));

vi.mock("@/lib/api-client", () => ({}));
vi.mock("@/lib/api/sdk.gen", () => ({
  getAssignableUsersImportsAssignableUsersGet: mocks.users,
  getUnmatchedOwnersImportsImportIdUnmatchedOwnersGet: mocks.groups,
  postAssignOwnerImportsImportIdAssignOwnerPost: mocks.assign,
}));

const USERS = [
  { id: "u1", email: "ann@example.test" },
  { id: "u2", email: "bob@example.test" },
];
const GROUPS = [
  { owner_group: "zed smith", display_name: "Zed Smith", lead_count: 12, is_blank: false },
  { owner_group: "", display_name: "", lead_count: 3, is_blank: true },
];

beforeEach(() => {
  vi.resetAllMocks();
  mocks.users.mockResolvedValue({ data: USERS, response: { status: 200 } });
  mocks.groups.mockResolvedValue({ data: GROUPS, response: { status: 200 } });
});

describe("UnmatchedOwnersPanel", () => {
  it("lists each owner text with its lead count and the blank group", async () => {
    render(<UnmatchedOwnersPanel importId="i" />);

    const zed = (await screen.findByText("Zed Smith")).closest("tr") as HTMLElement;
    expect(within(zed).getByText("12")).toBeInTheDocument();
    const blank = screen.getByText("(no owner given)").closest("tr") as HTMLElement;
    expect(within(blank).getByText("3")).toBeInTheDocument();
  });

  it("Assign stays disabled until a user is chosen", async () => {
    const user = userEvent.setup();
    render(<UnmatchedOwnersPanel importId="i" />);
    const select = await screen.findByLabelText("Assign Zed Smith to");
    const row = select.closest("tr") as HTMLElement;

    expect(within(row).getByRole("button", { name: "Assign" })).toBeDisabled();
    await user.selectOptions(select, "u2");
    expect(within(row).getByRole("button", { name: "Assign" })).toBeEnabled();
  });

  it("assigns a group, shows the counts and reloads the list", async () => {
    mocks.assign.mockResolvedValue({ data: { assigned: 11, skipped: 1 }, response: { status: 200 } });
    const user = userEvent.setup();
    render(<UnmatchedOwnersPanel importId="i" />);
    const select = await screen.findByLabelText("Assign Zed Smith to");
    await user.selectOptions(select, "u1");
    // After the assignment the server no longer lists that group.
    mocks.groups.mockResolvedValue({ data: [GROUPS[1]], response: { status: 200 } });

    await user.click(within(select.closest("tr") as HTMLElement).getByRole("button", { name: "Assign" }));

    expect(mocks.assign).toHaveBeenCalledWith({
      path: { import_id: "i" },
      body: { owner_group: "zed smith", user_id: "u1" },
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Assigned 11 leads; 1 already had an owner and were left as they are.",
    );
    expect(screen.queryByText("Zed Smith")).not.toBeInTheDocument();
  });

  it("assigns the blank group with an empty owner_group", async () => {
    mocks.assign.mockResolvedValue({ data: { assigned: 3, skipped: 0 }, response: { status: 200 } });
    const user = userEvent.setup();
    render(<UnmatchedOwnersPanel importId="i" />);
    const select = await screen.findByLabelText("Assign (no owner given) to");
    await user.selectOptions(select, "u2");

    await user.click(within(select.closest("tr") as HTMLElement).getByRole("button", { name: "Assign" }));

    expect(mocks.assign).toHaveBeenCalledWith({
      path: { import_id: "i" },
      body: { owner_group: "", user_id: "u2" },
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Assigned 3 leads.");
  });

  it("a refused assignment shows the server's message and keeps the list", async () => {
    mocks.assign.mockResolvedValue({
      error: { detail: "Choose an active user to assign the leads to.", code: "user_not_assignable" },
      response: { status: 422 },
    });
    const user = userEvent.setup();
    render(<UnmatchedOwnersPanel importId="i" />);
    const select = await screen.findByLabelText("Assign Zed Smith to");
    await user.selectOptions(select, "u1");

    await user.click(within(select.closest("tr") as HTMLElement).getByRole("button", { name: "Assign" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Choose an active user");
    expect(screen.getByText("Zed Smith")).toBeInTheDocument();
  });

  it("nothing unmatched: says every lead has an owner", async () => {
    mocks.groups.mockResolvedValue({ data: [], response: { status: 200 } });
    render(<UnmatchedOwnersPanel importId="i" />);

    expect(await screen.findByText("Every lead from this import has an owner.")).toBeInTheDocument();
  });
});
