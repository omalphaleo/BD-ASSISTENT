"""Unit tests for imports.layouts and the pure parts of imports.mapping (no database).

Needed because mapping must work for any source: headers are matched by normalized text (never
by position, D-040), Apollo headers are known, other providers' common names are recognised,
a missing header is left for the user (D-049), and a profile is only ever suggested when enough
headers overlap.
"""

import uuid

import pytest

from app.imports.layouts import (
    APOLLO_ALIASES,
    BUILTIN_ALIAS_LOOKUP,
    GENERIC_ALIASES,
    normalize_header,
)
from app.imports.mapping import (
    MIN_PROFILE_OVERLAP,
    MappedColumn,
    MappingColumn,
    MappingDefaults,
    MappingOrigin,
    apply_mapping,
    blocking_issues,
    suggest_columns,
    suggest_profiles,
)
from app.imports.models import SourceProfile
from app.leads.contracts import TARGET_FIELDS_BY_KEY


def test_normalize_header_ignores_case_punctuation_and_spacing() -> None:
    """E-mail Address, e mail  address and E-MAIL ADDRESS match; "# Employees" keeps its #."""
    assert normalize_header("E-mail Address") == normalize_header("  e mail   ADDRESS ")
    assert normalize_header("# Employees") == "# employees"
    assert normalize_header("   ") == ""


def test_every_alias_points_at_a_registry_key() -> None:
    """No built-in alias may name a field W2 would not understand."""
    for table in (APOLLO_ALIASES, GENERIC_ALIASES):
        assert set(table.values()) <= TARGET_FIELDS_BY_KEY.keys()
    assert BUILTIN_ALIAS_LOOKUP["email"] == "email"


def test_apollo_headers_map_by_name_in_any_column_order() -> None:
    """The same headers in a different order give the same targets: position is irrelevant."""
    headers = ["Last Name", "Email", "Secondary Email", "Mobile Phone", "# Employees", "Zzz"]
    columns = suggest_columns(headers, MappingDefaults())
    targets = {c.source_header: c.target_field for c in columns}
    assert targets == {
        "Last Name": "last_name",
        "Email": "email",
        "Secondary Email": "secondary_email",
        "Mobile Phone": "phone_mobile",
        "# Employees": "employee_count",
        "Zzz": None,
    }
    reversed_columns = suggest_columns(list(reversed(headers)), MappingDefaults())
    assert {c.source_header: c.target_field for c in reversed_columns} == targets


def test_other_provider_names_are_recognised() -> None:
    """Common non-Apollo spellings map to the same canonical fields."""
    columns = suggest_columns(["Work Email", "Given Name", "Surname", "Company"], MappingDefaults())
    assert [c.target_field for c in columns] == ["email", "first_name", "last_name", "company_name"]
    assert all(c.origin is MappingOrigin.BUILTIN for c in columns)


def test_profile_defaults_win_over_builtin_aliases() -> None:
    """An admin's saved default for "Company" overrides the built-in meaning."""
    defaults = MappingDefaults(columns={"company": "company_name_for_emails"})
    [column] = suggest_columns(["Company"], defaults)
    assert column.target_field == "company_name_for_emails"
    assert column.origin is MappingOrigin.PROFILE


def test_a_missing_header_is_left_unmapped_for_the_user() -> None:
    """A column with no header text is never guessed (D-049)."""
    [column] = suggest_columns([""], MappingDefaults())
    assert column.target_field is None


def test_two_columns_never_get_the_same_target() -> None:
    """When two headers match one field the first keeps it and the second is left unmapped."""
    columns = suggest_columns(["Email", "E-mail Address"], MappingDefaults())
    assert [c.target_field for c in columns] == ["email", None]


def test_defaults_reject_unknown_targets_and_extra_keys() -> None:
    """A hand-edited profile naming a field W2 does not know is invalid, not ignored."""
    with pytest.raises(ValueError, match="unknown target fields"):
        MappingDefaults(columns={"x": "not_a_field"})
    with pytest.raises(ValueError):
        MappingDefaults.model_validate({"version": 1, "surprise": 1})


def test_blocking_issues_name_each_unmapped_mandatory_field() -> None:
    """Without email and first_name columns both are reported (D-069); the file is not rejected."""
    columns = [MappingColumn(0, "Title", "title", MappingOrigin.BUILTIN)]
    assert set(blocking_issues(columns)) == {"email_not_mapped", "first_name_not_mapped"}
    columns += [
        MappingColumn(1, "Email", "email", MappingOrigin.BUILTIN),
        MappingColumn(2, "First Name", "first_name", MappingOrigin.BUILTIN),
    ]
    assert blocking_issues(columns) == ()


def _profile(name: str, columns: dict[str, str]) -> SourceProfile:
    """An in-memory profile (never added to a session) with the given saved headers."""
    return SourceProfile(
        id=uuid.uuid4(),
        name=name,
        layout="x",
        is_active=True,
        mapping_defaults={"version": 1, "columns": columns, "formats": {}},
    )


def test_profiles_are_suggested_only_with_enough_header_overlap() -> None:
    """Overlap below the minimum gives no suggestion; the best match is listed first."""
    headers = ["Email", "Name", "Phone", "City"]
    good = _profile("good", {"email": "email", "name": "first_name", "phone": "phone_mobile"})
    weak = _profile("weak", {"email": "email"})
    suggestions = suggest_profiles(headers, [weak, good])
    assert [s.name for s in suggestions] == ["good"]
    assert suggestions[0].overlap == 0.75
    assert 0.25 < MIN_PROFILE_OVERLAP <= 0.75


def test_a_broken_profile_is_never_suggested() -> None:
    """A profile whose JSON no longer matches the version-1 shape is skipped, not fatal."""
    broken = SourceProfile(
        id=uuid.uuid4(), name="broken", layout="x", is_active=True, mapping_defaults={"bad": 1}
    )
    assert suggest_profiles(["Email"], [broken]) == []


def test_apply_mapping_builds_source_row_values_and_keeps_the_raw_email() -> None:
    """Mapped cells become typed values; the email text is also returned exactly as received."""
    columns = [
        MappedColumn(0, "email"),
        MappedColumn(1, "first_name"),
        MappedColumn(2, "employee_count"),
        MappedColumn(3, "email_sent"),
    ]
    row = apply_mapping([" Ada@Example.com ", "Ada", "1,200", "maybe"], columns, {})
    assert row.values == {
        "email": "Ada@Example.com",
        "first_name": "Ada",
        "employee_count": 1200,
        "email_sent": None,
    }
    assert row.raw_email == " Ada@Example.com "
    assert [(w.field, w.code) for w in row.warnings] == [("email_sent", "not_a_boolean")]


def test_apply_mapping_tolerates_short_rows() -> None:
    """A row with fewer cells than the header gives None for the missing ones, no crash."""
    row = apply_mapping(["a@example.com"], [MappedColumn(0, "email"), MappedColumn(5, "title")], {})
    assert row.values == {"email": "a@example.com", "title": None}
    assert row.warnings == ()
