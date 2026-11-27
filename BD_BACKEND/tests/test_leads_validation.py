"""Tests for validate_row in app.leads.validation (M2-B1).

Needed because the quarantine decision is the core of import module C: only a usable work
email and a first name are mandatory (D-069), unusable emails are quarantined with a reason
(D-042, D-072), and everything else must never block a row (D-070, D-071). One test per
reason and per non-reason keeps these business rules from drifting.
"""

import pytest

from app.leads.validation import RowIssue, RowWarning, validate_row


def test_valid_row_has_no_issues() -> None:
    """A work email plus a first name: valid, normalized, no issues or warnings."""
    result = validate_row("  JANE ", [" Jane.Doe@Acme.com "])

    assert result.is_valid
    assert result.issues == ()
    assert result.warnings == ()
    assert result.work_email == "jane.doe@acme.com"
    assert result.first_name == "Jane"


def test_personal_email_only_is_quarantined() -> None:
    """Only a free-mail address: personal_email_only, and no work email is chosen."""
    result = validate_row("Jane", ["jane@gmail.com"])

    assert result.issues == (RowIssue.PERSONAL_EMAIL_ONLY,)
    assert result.work_email is None
    assert not result.is_valid


def test_generic_email_only_is_quarantined() -> None:
    """Only a role address such as info@: generic_email_only."""
    result = validate_row("Jane", ["info@acme.com"])

    assert result.issues == (RowIssue.GENERIC_EMAIL_ONLY,)


def test_bad_email_format_is_quarantined() -> None:
    """An email that is not shaped like an address: bad_email_format."""
    result = validate_row("Jane", ["jane.at.acme.com"])

    assert result.issues == (RowIssue.BAD_EMAIL_FORMAT,)


@pytest.mark.parametrize("emails", [[], [None], ["", "   "]])
def test_no_email_at_all_is_quarantined(emails: list[str | None]) -> None:
    """No email cell with any content: no_work_email (not a format or personal reason)."""
    result = validate_row("Jane", emails)

    assert result.issues == (RowIssue.NO_WORK_EMAIL,)


def test_each_unusable_email_kind_is_reported_in_fixed_order() -> None:
    """A personal, a generic and a malformed address together give all three reasons in order."""
    result = validate_row("Jane", ["bad", "info@acme.com", "jane@gmail.com"])

    assert result.issues == (
        RowIssue.PERSONAL_EMAIL_ONLY,
        RowIssue.GENERIC_EMAIL_ONLY,
        RowIssue.BAD_EMAIL_FORMAT,
    )


def test_work_email_beats_personal_secondary_email() -> None:
    """A row with a work email and a personal one is valid; the personal one does not matter."""
    result = validate_row("Jane", ["jane@gmail.com", "jane@acme.com"])

    assert result.is_valid
    assert result.work_email == "jane@acme.com"


def test_first_work_email_wins() -> None:
    """With two work emails, the first in priority order is the one used."""
    result = validate_row("Jane", ["a@one.com", "b@two.com"])

    assert result.work_email == "a@one.com"


@pytest.mark.parametrize("first_name", [None, "", "   ", "-", "123"])
def test_missing_or_non_name_first_name_is_quarantined(first_name: str | None) -> None:
    """A blank first name, or one with no letters, gives missing_first_name (D-069)."""
    result = validate_row(first_name, ["jane@acme.com"])

    assert result.issues == (RowIssue.MISSING_FIRST_NAME,)
    assert result.first_name is None
    assert result.work_email == "jane@acme.com"


def test_email_and_first_name_problems_are_both_reported() -> None:
    """A row failing both mandatory rules lists both reasons."""
    result = validate_row(None, ["jane@gmail.com"])

    assert result.issues == (RowIssue.PERSONAL_EMAIL_ONLY, RowIssue.MISSING_FIRST_NAME)


@pytest.mark.parametrize("status", ["Unverified", " unverified ", "UNVERIFIED"])
def test_apollo_unverified_email_is_a_warning_only(status: str) -> None:
    """An Apollo-unverified work email stays valid and only adds a warning (D-042)."""
    result = validate_row("Jane", ["jane@acme.com"], work_email_status=status)

    assert result.is_valid
    assert result.warnings == (RowWarning.UNVERIFIED_EMAIL,)


@pytest.mark.parametrize("status", [None, "Verified", ""])
def test_verified_or_missing_status_has_no_warning(status: str | None) -> None:
    """A verified, empty or missing email status adds no warning."""
    result = validate_row("Jane", ["jane@acme.com"], work_email_status=status)

    assert result.warnings == ()


def test_validation_never_raises_on_odd_input() -> None:
    """Strange cell content produces issues, never an exception (D-068: no file fails)."""
    result = validate_row("\t\n", ["@@@", "\x00"])

    assert RowIssue.MISSING_FIRST_NAME in result.issues
    assert RowIssue.BAD_EMAIL_FORMAT in result.issues
