"""Unit tests for imports.conversion: cell-to-JSON type conversion and the field registry.

Needed because every source (Apollo, other providers, hand-made sheets) writes numbers, flags
and dates differently, and the mapping step must hand W2 clean JSON types without ever guessing:
an unreadable cell has to become None plus a warning, never a wrong value. No database is used.
"""

from datetime import date, datetime

import pytest

from app.imports.conversion import (
    FieldFormat,
    convert_cell,
    is_blank,
)
from app.leads.contracts import (
    REQUIRED_FIELD_KEYS,
    TARGET_FIELDS,
    TARGET_FIELDS_BY_KEY,
    FieldType,
)


@pytest.mark.parametrize("cell", [None, "", "   ", "\t"])
def test_blank_cells_give_none_and_no_warning(cell: object) -> None:
    """A blank cell is a missing value, not a problem: None for every type, no warning."""
    assert is_blank(cell)
    for value_type in FieldType:
        result = convert_cell(cell, value_type)
        assert result.value is None
        assert result.warning is None


def test_text_is_trimmed_and_whole_floats_lose_the_decimal_point() -> None:
    """Excel stores 5 as 5.0: a text field reads it back as "5", and text is trimmed."""
    assert convert_cell("  Ada ", FieldType.TEXT).value == "Ada"
    assert convert_cell(5.0, FieldType.TEXT).value == "5"
    assert convert_cell(5.5, FieldType.TEXT).value == "5.5"


@pytest.mark.parametrize(
    ("cell", "expected"),
    [("1,200", 1200), (" 42 ", 42), ("12.0", 12), (7, 7), (7.0, 7), ("-3", -3)],
)
def test_integer_accepts_whole_numbers(cell: object, expected: int) -> None:
    """Whole numbers in common spellings convert to int."""
    result = convert_cell(cell, FieldType.INTEGER)
    assert result.value == expected
    assert result.warning is None


@pytest.mark.parametrize("cell", ["12.5", "many", True, "1e3", "5M"])
def test_integer_rejects_everything_else_with_a_warning(cell: object) -> None:
    """Fractions, words, booleans and shorthand are not guessed: None plus not_an_integer."""
    result = convert_cell(cell, FieldType.INTEGER)
    assert result.value is None
    assert result.warning == "not_an_integer"


def test_decimal_reads_both_separator_styles_when_the_profile_declares_one() -> None:
    """ "1,234.5" is read with the default format; "1.234,5" only when the profile says so."""
    assert convert_cell("1,234.5", FieldType.DECIMAL).value == 1234.5
    comma = FieldFormat(decimal_separator=",")
    assert convert_cell("1.234,5", FieldType.DECIMAL, comma).value == 1234.5
    assert convert_cell(3, FieldType.DECIMAL).value == 3.0


@pytest.mark.parametrize("cell", ["$5", "5M", "abc", False])
def test_decimal_does_not_guess_currency_or_shorthand(cell: object) -> None:
    """Currency symbols and "5M" are not interpreted: None plus not_a_number."""
    result = convert_cell(cell, FieldType.DECIMAL)
    assert result.value is None
    assert result.warning == "not_a_number"


@pytest.mark.parametrize(
    ("cell", "expected"),
    [("Yes", True), ("TRUE", True), ("1", True), ("n", False), ("False", False), (True, True)],
)
def test_boolean_words(cell: object, expected: bool) -> None:
    """Yes/no style words in any case, and real booleans, convert."""
    assert convert_cell(cell, FieldType.BOOLEAN).value is expected


def test_boolean_rejects_unknown_words() -> None:
    """ "maybe" is not guessed: None plus not_a_boolean."""
    result = convert_cell("maybe", FieldType.BOOLEAN)
    assert result.value is None
    assert result.warning == "not_a_boolean"


def test_datetime_returns_iso_text_without_adding_a_zone() -> None:
    """ISO text, Excel datetimes and dates all become ISO-8601 text; W2 attaches the zone."""
    assert convert_cell("2026-03-04", FieldType.DATETIME).value == "2026-03-04T00:00:00"
    assert (
        convert_cell(datetime(2026, 3, 4, 5, 6), FieldType.DATETIME).value == "2026-03-04T05:06:00"
    )
    assert convert_cell(date(2026, 3, 4), FieldType.DATETIME).value == "2026-03-04"


def test_datetime_uses_the_profile_format_and_never_guesses_day_or_month() -> None:
    """04/03/2026 is only read when the profile declares %d/%m/%Y; otherwise it is a warning."""
    undeclared = convert_cell("04/03/2026", FieldType.DATETIME)
    assert undeclared.value is None
    assert undeclared.warning == "not_a_date"
    declared = convert_cell("04/03/2026", FieldType.DATETIME, FieldFormat(date_format="%d/%m/%Y"))
    assert declared.value == "2026-03-04T00:00:00"


def test_registry_keys_are_unique_snake_case_and_required_fields_are_d069() -> None:
    """The registry has no duplicate keys, and only email and first_name are required (D-069)."""
    keys = [field.key for field in TARGET_FIELDS]
    assert len(keys) == len(set(keys)) == len(TARGET_FIELDS_BY_KEY)
    assert all(key == key.lower() and " " not in key for key in keys)
    assert set(REQUIRED_FIELD_KEYS) == {"email", "first_name"}


def test_registry_covers_every_apollo_email_and_phone_column() -> None:
    """Primary, secondary and tertiary emails and all five phone columns have a target key."""
    expected = {
        "email", "email_status", "email_source", "email_verification_source",
        "email_confidence", "email_catch_all_status", "email_last_verified_at",
        "secondary_email", "secondary_email_status", "secondary_email_source",
        "secondary_email_verification_source", "tertiary_email", "tertiary_email_status",
        "tertiary_email_source", "tertiary_email_verification_source",
        "phone_work_direct", "phone_home", "phone_mobile", "phone_corporate", "phone_other",
        "company_phone", "do_not_call",
    }  # fmt: skip
    assert expected <= TARGET_FIELDS_BY_KEY.keys()
