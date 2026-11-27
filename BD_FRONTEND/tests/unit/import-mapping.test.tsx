/**
 * Component tests for the profile and mapping steps of the import wizard (task M2-A2 UI).
 *
 * Needed so the confirm-before-apply profile suggestion, the missing-header fix (D-049), the
 * blocking issues (D-069) and the admin-only save-as-default cannot regress. The generated API
 * functions and the current user are faked; no request is sent and the data is synthetic.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MappingStep from "@/components/import/MappingStep";
import ProfileStep from "@/components/import/ProfileStep";

const mocks = vi.hoisted(() => ({
  profiles: vi.fn(),
  targets: vi.fn(),
  readMapping: vi.fn(),
  putMapping: vi.fn(),
  setProfile: vi.fn(),
  saveDefault: vi.fn(),
  role: { value: "rep" },
}));

vi.mock("@/lib/api-client", () => ({}));
vi.mock("@/lib/auth-context", () => ({
  useCurrentUser: () => ({ id: "u", email: "u@example.test", role: mocks.role.value }),
}));
vi.mock("@/lib/api/sdk.gen", () => ({
  listProfileOptionsImportsProfilesGet: mocks.profiles,
  listTargetFieldsImportsTargetFieldsGet: mocks.targets,
  readMappingImportsImportIdMappingGet: mocks.readMapping,
  putMappingImportsImportIdMappingPut: mocks.putMapping,
  setImportProfileImportsImportIdProfilePut: mocks.setProfile,
  saveAsProfileDefaultImportsImportIdMappingSaveAsDefaultPost: mocks.saveDefault,
}));

const IMPORT_ID = "11111111-1111-1111-1111-111111111111";
const PROFILE = { id: "22222222-2222-2222-2222-222222222222", name: "Apollo export", layout: "apollo" };
const FIELDS = [
  { key: "first_name", label: "First name", group: "person", value_type: "text", required: true },
  { key: "email", label: "Email", group: "email", value_type: "text", required: true },
];
const MAPPING = {
  import_id: IMPORT_ID,
  is_saved: false,
  blocking_issues: [],
  profile_suggestions: [{ source_profile_id: PROFILE.id, name: PROFILE.name, overlap: 0.9 }],
  columns: [
    { column_index: 0, source_header: "Email", target_field: "email", origin: "builtin", is_reassigned: false },
    { column_index: 1, source_header: "", target_field: null, origin: "unmapped", is_reassigned: false },
  ],
};

beforeEach(() => {
  vi.resetAllMocks();
  mocks.role.value = "rep";
  mocks.profiles.mockResolvedValue({ data: [PROFILE], response: { status: 200 } });
  mocks.targets.mockResolvedValue({ data: FIELDS, response: { status: 200 } });
  mocks.readMapping.mockResolvedValue({ data: MAPPING, response: { status: 200 } });
});

describe("ProfileStep", () => {
  it("suggested profile: not applied until clicked, then sent with the trimmed country", async () => {
    mocks.setProfile.mockResolvedValue({ data: {}, response: { status: 200 } });
    const onDone = vi.fn();
    const user = userEvent.setup();
    render(<ProfileStep importId={IMPORT_ID} onDone={onDone} />);

    expect(await screen.findByText(/90% of its columns match/)).toBeInTheDocument();
    expect(screen.getByLabelText("Source profile")).toHaveValue(""); // nothing auto-applied
    await user.click(screen.getByRole("button", { name: "Use this profile" }));
    await user.type(screen.getByLabelText("Default country (optional)"), "  India ");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(mocks.setProfile.mock.calls[0][0].body).toEqual({
      source_profile_id: PROFILE.id,
      default_country: "India",
    });
  });

  it("server refusal: shows the fixed message and does not continue", async () => {
    mocks.setProfile.mockResolvedValue({
      error: { detail: "That profile cannot be used.", code: "invalid_profile" },
      response: { status: 409 },
    });
    const onDone = vi.fn();
    const user = userEvent.setup();
    render(<ProfileStep importId={IMPORT_ID} onDone={onDone} />);
    await user.click(await screen.findByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("That profile cannot be used.");
    expect(onDone).not.toHaveBeenCalled();
  });
});

describe("MappingStep", () => {
  it("headerless column: hinted, can be assigned, and the save body carries the choice", async () => {
    mocks.putMapping.mockResolvedValue({
      data: { ...MAPPING, is_saved: true, blocking_issues: ["first_name_not_mapped"] },
      response: { status: 200 },
    });
    const user = userEvent.setup();
    render(<MappingStep importId={IMPORT_ID} onDone={vi.fn()} />);

    expect(await screen.findByText(/No header: assign a field/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/column 2: \(no header\)/), "first_name");
    await user.click(screen.getByRole("button", { name: "Save mapping" }));

    await waitFor(() => expect(mocks.putMapping).toHaveBeenCalled());
    expect(mocks.putMapping.mock.calls[0][0].body.columns).toEqual([
      { column_index: 0, target_field: "email" },
      { column_index: 1, target_field: "first_name" },
    ]);
    // The server still reports first name as unmapped here, so the blocking text shows.
    expect(await screen.findByText(/No column is mapped to First name/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("saved with no blocking issue: Continue is enabled and moves on", async () => {
    mocks.putMapping.mockResolvedValue({
      data: { ...MAPPING, is_saved: true },
      response: { status: 200 },
    });
    const onDone = vi.fn();
    const user = userEvent.setup();
    render(<MappingStep importId={IMPORT_ID} onDone={onDone} />);
    await user.click(await screen.findByRole("button", { name: "Save mapping" }));
    await user.click(await screen.findByRole("button", { name: "Continue" }));

    expect(onDone).toHaveBeenCalled();
  });

  it("same field on two columns: hint shown; server 422 message is displayed on save", async () => {
    mocks.putMapping.mockResolvedValue({
      error: { detail: "A field can be used by one column only.", code: "invalid_mapping" },
      response: { status: 422 },
    });
    const user = userEvent.setup();
    render(<MappingStep importId={IMPORT_ID} onDone={vi.fn()} />);
    await user.selectOptions(await screen.findByLabelText(/column 2: \(no header\)/), "email");

    // Both columns that share the field carry the hint.
    expect(screen.getAllByText(/Used by more than one column/)).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Save mapping" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A field can be used by one column only.");
  });

  it("rep: the save-as-default action is not shown", async () => {
    render(<MappingStep importId={IMPORT_ID} onDone={vi.fn()} />);
    await screen.findByText("Map the columns");

    expect(screen.queryByRole("button", { name: "Save as profile default" })).toBeNull();
  });

  it("admin: save-as-default is available after saving and sends the chosen profile", async () => {
    mocks.role.value = "admin";
    mocks.putMapping.mockResolvedValue({ data: { ...MAPPING, is_saved: true }, response: { status: 200 } });
    mocks.saveDefault.mockResolvedValue({
      data: { source_profile_id: PROFILE.id, columns_in_defaults: 2 },
      response: { status: 200 },
    });
    const user = userEvent.setup();
    render(<MappingStep importId={IMPORT_ID} onDone={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Save mapping" }));
    await user.click(await screen.findByRole("button", { name: "Save as profile default" }));

    expect(await screen.findByText(/Saved as the profile default \(2 columns\)/)).toBeInTheDocument();
    expect(mocks.saveDefault.mock.calls[0][0].body).toEqual({ source_profile_id: PROFILE.id });
  });
});
