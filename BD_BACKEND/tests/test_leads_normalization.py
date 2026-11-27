"""Tests for the pure normalization functions in app.leads.normalization (M2-B1).

Needed because every import row passes through these functions before validation and
matching; each rule (D-069, D-070, D-071, D-072, D-076, D-078) gets table-driven synthetic
cases, including awkward inputs, so a regression in cleaning is caught without real data.
"""

import pytest

from app.leads.normalization import (
    STANDARD_INDUSTRY_MAP,
    EmailKind,
    classify_email,
    derive_company_name,
    email_domain,
    has_letters,
    is_valid_email_format,
    normalize_country,
    normalize_domain,
    normalize_email_address,
    normalize_industry,
    normalize_name,
    normalize_state,
)
from app.leads.reference_data import INDUSTRY_ALIASES, NAICS_SECTORS, UNKNOWN_INDUSTRY


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Jane.Doe@ACME.com ", "jane.doe@acme.com"),
        ("a@b.co", "a@b.co"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_normalize_email_address(raw: str | None, expected: str | None) -> None:
    """Emails are trimmed and lowercased; blank or missing cells become None."""
    assert normalize_email_address(raw) == expected


@pytest.mark.parametrize(
    ("email", "valid"),
    [
        ("jane@acme.com", True),
        ("jane@mail.acme.co.uk", True),
        ("not-an-email", False),
        ("jane@acme", False),
        ("jane@@acme.com", False),
        ("jane doe@acme.com", False),
        ("@acme.com", False),
        ("jane@acme.", False),
    ],
)
def test_is_valid_email_format(email: str, valid: bool) -> None:
    """Only addresses shaped local@domain.tld without spaces pass the format check."""
    assert is_valid_email_format(email) is valid


def test_email_domain() -> None:
    """The domain is the text after the @; a malformed address has no domain."""
    assert email_domain("jane@acme.com") == "acme.com"
    assert email_domain("garbage") is None


@pytest.mark.parametrize(
    ("email", "kind"),
    [
        ("jane.doe@acme.com", EmailKind.WORK),
        ("jane@gmail.com", EmailKind.PERSONAL),
        ("jane@yahoo.co.uk", EmailKind.PERSONAL),
        ("info@acme.com", EmailKind.GENERIC),
        ("sales@acme.com", EmailKind.GENERIC),
        ("support+eu@acme.com", EmailKind.GENERIC),
        # A free-mail domain wins over a generic prefix: it is not a company mailbox.
        ("info@gmail.com", EmailKind.PERSONAL),
        ("not-an-email", EmailKind.INVALID),
        # A real person's name that merely starts like a prefix is still a work email.
        ("information.officer@acme.com", EmailKind.WORK),
    ],
)
def test_classify_email(email: str, kind: EmailKind) -> None:
    """Each address is classified as invalid, personal, generic or work, in that priority."""
    assert classify_email(email) is kind


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.Acme.com/about", "acme.com"),
        ("HTTP://acme.com", "acme.com"),
        ("www.acme.com", "acme.com"),
        ("acme.com.", "acme.com"),
        ("acme.com/path?x=1", "acme.com"),
        ("  ", None),
        (None, None),
    ],
)
def test_normalize_domain(raw: str | None, expected: str | None) -> None:
    """Websites reduce to a bare lowercase domain; blank cells become None."""
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("jane", "Jane"),
        ("JANE", "Jane"),
        ("  jean-luc ", "Jean-Luc"),
        ("o'brien", "O'Brien"),
        ("McDonald", "McDonald"),
        ("van der Berg", "van der Berg"),
        ("Mary   Ann", "Mary Ann"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_name(raw: str | None, expected: str | None) -> None:
    """All-lower or all-upper names get proper case; mixed-case names are left alone."""
    assert normalize_name(raw) == expected


def test_has_letters() -> None:
    """A value with no letter in it ("-", "123") is not a name."""
    assert has_letters("Jane")
    assert not has_letters("-")
    assert not has_letters("123")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("usa", "United States"),
        ("U.S.", "United States"),
        ("United States of America", "United States"),
        ("uk", "United Kingdom"),
        ("Germany", "Germany"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_country(raw: str | None, expected: str | None) -> None:
    """Known country wordings map to one standard name; unknown ones are kept as given."""
    assert normalize_country(raw) == expected


@pytest.mark.parametrize(
    ("raw", "country", "expected"),
    [
        ("ca", "United States", "California"),
        ("CALIFORNIA", "United States", "California"),
        ("tx", "United States", "Texas"),
        ("Atlantis", "United States", "Atlantis"),
        # Outside the US the abbreviation table must not be applied ("ca" is not California).
        ("ca", "Canada", "ca"),
        ("ca", None, "ca"),
        ("", "United States", None),
        (None, "United States", None),
    ],
)
def test_normalize_state(raw: str | None, country: str | None, expected: str | None) -> None:
    """US states map to their standard name; other countries and unknown values are kept."""
    assert normalize_state(raw, country) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Software", "Information"),
        ("  FINANCIAL SERVICES ", "Finance and Insurance"),
        ("Utilities", "Utilities"),
        ("Space Tourism", "Space Tourism"),
        ("", UNKNOWN_INDUSTRY),
        ("   ", UNKNOWN_INDUSTRY),
        (None, UNKNOWN_INDUSTRY),
    ],
)
def test_normalize_industry(raw: str | None, expected: str) -> None:
    """Industries map to a NAICS sector; unmapped text is kept; missing becomes Unknown."""
    assert normalize_industry(raw) == expected


def test_normalize_industry_uses_supplied_mappings() -> None:
    """A caller-supplied map (for example database mappings) replaces the starter map."""
    assert normalize_industry("Widgets", {"widgets": "Manufacturing"}) == "Manufacturing"


def test_industry_aliases_point_at_real_sectors() -> None:
    """Every alias must map to a NAICS sector name, or the seed would fail on its lookup."""
    sector_names = {name for _, name in NAICS_SECTORS}
    assert set(INDUSTRY_ALIASES.values()) <= sector_names
    assert set(STANDARD_INDUSTRY_MAP.values()) <= sector_names


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("jane@acme-corp.com", "Acme Corp"),
        ("jane@acme.com", "Acme"),
        ("jane@mail.acme.io", "Acme"),
        ("jane@acme.co.uk", "Acme"),
        ("jane@big_co.com", "Big Co"),
        ("garbage", None),
    ],
)
def test_derive_company_name(email: str, expected: str | None) -> None:
    """The company name comes from the domain label before the public suffix (D-071)."""
    assert derive_company_name(email) == expected
