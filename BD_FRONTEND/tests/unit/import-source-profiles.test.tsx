/**
 * Component tests for the source profile admin (task M2-A6 UI).
 *
 * Needed so list, create, rename, deactivate-with-warning and saved-column removal behave as the
 * server contract says, and the server's fixed refusal messages reach the admin. The generated
 * client is faked; no network is used.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SourceProfilesAdmin from "@/components/import/SourceProfilesAdmin";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  read: vi.fn(),
  edit: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({}));
vi.mock("@/lib/api/sdk.gen", () => ({
  listSourceProfilesSourceProfilesGet: mocks.list,
  createSourceProfileSourceProfilesPost: mocks.create,
  readSourceProfileSourceProfilesProfileIdGet: mocks.read,
  editSourceProfileSourceProfilesProfileIdPatch: mocks.edit,
  removeSourceProfileColumnsSourceProfilesProfileIdRemoveColumnsPost: mocks.remove,
}));

/** A profile in list shape. */
function summary(extra: Record<string, unknown> = {}) {
  return {
    id: "p1",
    name: "Apollo EU",
    layout: "apollo",
    is_active: true,
    saved_column_count: 2,
    defaults_valid: true,
    created_at: "2026-11-27T00:00:00Z",
    updated_at: "2026-11-27T00:00:00Z",
    ...extra,
  };
}

/** A profile in detail shape, with two saved headers. */
function detail(extra: Record<string, unknown> = {}) {
  return {
    ...summary(),
    columns: { "First Name": "first_name", Email: "email" },
    warnings: [],
    ...extra,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.list.mockResolvedValue({ data: [summary()], response: { status: 200 } });
  mocks.read.mockResolvedValue({ data: detail(), response: { status: 200 } });
});

describe("SourceProfilesAdmin", () => {
  it("lists profiles with status and saved column count", async () => {
    render(<SourceProfilesAdmin />);

    expect(await screen.findByText("Apollo EU")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("creates a profile, opens it and reloads the list", async () => {
    mocks.create.mockResolvedValue({ data: detail({ id: "p2", name: "New" }), response: { status: 201 } });
    const user = userEvent.setup();
    render(<SourceProfilesAdmin />);
    await screen.findByText("Apollo EU");

    await user.type(screen.getByLabelText("Name"), " New ");
    await user.type(screen.getByLabelText("Layout label"), "custom");
    await user.click(screen.getByRole("button", { name: "Create profile" }));

    expect(mocks.create).toHaveBeenCalledWith({ body: { name: "New", layout: "custom" } });
    expect(await screen.findByRole("region", { name: "Profile Apollo EU" })).toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledTimes(2);
  });

  it("a taken name shows the server's fixed message and creates nothing", async () => {
    mocks.create.mockResolvedValue({
      error: { detail: "A profile with this name already exists.", code: "duplicate_name" },
      response: { status: 409 },
    });
    const user = userEvent.setup();
    render(<SourceProfilesAdmin />);
    await screen.findByText("Apollo EU");

    await user.type(screen.getByLabelText("Name"), "apollo eu");
    await user.click(screen.getByRole("button", { name: "Create profile" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A profile with this name already exists.",
    );
  });

  it("deactivating shows the server's warning and does not block", async () => {
    mocks.edit.mockResolvedValue({
      data: detail({ is_active: false, warnings: ["2 imports in progress use this profile."] }),
      response: { status: 200 },
    });
    const user = userEvent.setup();
    render(<SourceProfilesAdmin />);
    await user.click(await screen.findByRole("button", { name: "Open" }));

    await user.click(await screen.findByRole("button", { name: "Deactivate" }));

    expect(mocks.edit).toHaveBeenCalledWith({
      path: { profile_id: "p1" },
      body: { is_active: false },
    });
    expect(await screen.findByRole("status")).toHaveTextContent("2 imports in progress");
    expect(screen.getByRole("button", { name: "Activate" })).toBeInTheDocument();
  });

  it("removing a saved column sends that header and shows the trimmed list", async () => {
    mocks.remove.mockResolvedValue({
      data: detail({ columns: { Email: "email" } }),
      response: { status: 200 },
    });
    const user = userEvent.setup();
    render(<SourceProfilesAdmin />);
    await user.click(await screen.findByRole("button", { name: "Open" }));

    await user.click(await screen.findByRole("button", { name: "Remove First Name" }));

    expect(mocks.remove).toHaveBeenCalledWith({
      path: { profile_id: "p1" },
      body: { headers: ["First Name"] },
    });
    expect(screen.queryByRole("button", { name: "Remove First Name" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove Email" })).toBeInTheDocument();
  });

  it("an unreachable server shows the fallback message instead of an empty list", async () => {
    mocks.list.mockResolvedValue({ error: undefined, response: undefined });
    render(<SourceProfilesAdmin />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the server");
  });
});
