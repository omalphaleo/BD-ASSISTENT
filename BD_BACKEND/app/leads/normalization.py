"""Pure cleaning functions for imported lead values: emails, domains, names, places, industry.

Needed so every row is tidied the same way before validation, matching and merge (M2 modules
C and D): matching compares normalized emails and domains, and validation classifies emails
with classify_email(). The functions take plain values and return plain values, never touch
the database or the clock, and never raise on bad input; a bad value comes back as None or
as an EmailKind, so one broken cell cannot fail an import (D-068).
"""

import re
from collections.abc import Mapping
from enum import StrEnum

from app.core.services import normalize_email
from app.leads.reference_data import (
    COUNTRY_ALIASES,
    GENERIC_EMAIL_PREFIXES,
    INDUSTRY_ALIASES,
    NAICS_SECTORS,
    PERSONAL_EMAIL_DOMAINS,
    SECOND_LEVEL_DOMAIN_SUFFIXES,
    UNITED_STATES,
    UNKNOWN_INDUSTRY,
    US_STATES,
)

# Deliberately simple shape check: one "@", no spaces, and a dotted domain. Full RFC
# validation is not wanted; real deliverability is checked by Apollo and by bounces.
_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s.]+$")
_SCHEME_PREFIX = re.compile(r"^[a-z][a-z0-9+.-]*://")
_LETTER_RUN = re.compile(r"[A-Za-z]+")
_WHITESPACE_RUN = re.compile(r"\s+")
_NON_NAME_CHARACTERS = re.compile(r"[^a-z0-9 ]+")
# Legal-form words dropped from the end of a company name so "Acme Inc." equals "Acme".
_COMPANY_SUFFIXES = frozenset(
    {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "gmbh", "plc"}
)

# Industry lookup used when no database mappings are supplied: NAICS sector names (lowercase)
# map to themselves, and the known source wordings map to their sector.
STANDARD_INDUSTRY_MAP: dict[str, str] = {
    **{name.lower(): name for _, name in NAICS_SECTORS},
    **INDUSTRY_ALIASES,
}

_US_STATE_LOOKUP: dict[str, str] = {
    **{abbreviation.lower(): name for abbreviation, name in US_STATES.items()},
    **{name.lower(): name for name in US_STATES.values()},
}


class EmailKind(StrEnum):
    """What an email address is for outreach purposes (D-069, D-072)."""

    WORK = "work"
    PERSONAL = "personal"
    GENERIC = "generic"
    INVALID = "invalid"


def _clean_text(raw: str | None) -> str | None:
    """Trim and collapse inner whitespace; return None for missing or blank text."""
    if raw is None:
        return None
    text = _WHITESPACE_RUN.sub(" ", raw).strip()
    return text or None


def normalize_email_address(raw: str | None) -> str | None:
    """Trim and lowercase an email; None when the cell is missing or blank."""
    text = _clean_text(raw)
    return normalize_email(text) if text is not None else None


def is_valid_email_format(email: str) -> bool:
    """Tell whether a normalized email has the shape local@domain.tld (no spaces)."""
    return _EMAIL_SHAPE.match(email) is not None


def email_domain(email: str) -> str | None:
    """Return the domain of a well-formed normalized email, or None if it is malformed."""
    if not is_valid_email_format(email):
        return None
    return email.rsplit("@", 1)[1]


def classify_email(email: str) -> EmailKind:
    """Classify a normalized email as invalid, personal, generic or work (D-069, D-072).

    Order matters: a badly formed address is invalid whatever its domain; a free-mail domain
    is personal even when the prefix is generic (info@gmail.com is not a company mailbox);
    only then is the prefix compared with the role-address list.
    """
    domain = email_domain(email)
    if domain is None:
        return EmailKind.INVALID
    if domain in PERSONAL_EMAIL_DOMAINS:
        return EmailKind.PERSONAL
    # "sales+eu@acme.com" is the same role mailbox as "sales@acme.com".
    local_part = email.rsplit("@", 1)[0].split("+", 1)[0]
    if local_part in GENERIC_EMAIL_PREFIXES:
        return EmailKind.GENERIC
    return EmailKind.WORK


def normalize_domain(raw: str | None) -> str | None:
    """Reduce a website or domain cell to a bare lowercase domain.

    "https://www.Acme.com/about" and "acme.com." both become "acme.com".

    Returns:
        The domain, or None when the cell is missing or empty after cleaning.
    """
    text = _clean_text(raw)
    if text is None:
        return None
    text = _SCHEME_PREFIX.sub("", text.lower())
    text = re.split(r"[/?#]", text, maxsplit=1)[0]
    text = text.removeprefix("www.").rstrip(".")
    return text or None


def normalize_name(raw: str | None) -> str | None:
    """Tidy a person name: collapse spaces, and fix case only when it is all lower or all upper.

    Mixed-case names ("McDonald", "van der Berg") are left alone because guessing would
    damage them; "JANE", "jane" and "o'brien" become "Jane" and "O'Brien".

    Returns:
        The cleaned name, or None when the cell is missing or blank.
    """
    text = _clean_text(raw)
    if text is None:
        return None
    if text.islower() or text.isupper():
        return _LETTER_RUN.sub(lambda match: match.group().capitalize(), text)
    return text


def has_letters(text: str) -> bool:
    """Tell whether text contains at least one letter (so "-" or "123" is not a name)."""
    return any(character.isalpha() for character in text)


def normalize_country(raw: str | None) -> str | None:
    """Map a country wording ("usa", "U.S.") to its standard name; unknown ones stay as given."""
    text = _clean_text(raw)
    if text is None:
        return None
    return COUNTRY_ALIASES.get(text.lower(), text)


def normalize_state(raw: str | None, country: str | None) -> str | None:
    """Map a US state abbreviation or name ("ca", "CALIFORNIA") to its standard name.

    Only United States states are known (D-078); for any other country, or an unknown
    value, the cleaned text is kept so no data is lost.
    """
    text = _clean_text(raw)
    if text is None:
        return None
    if country == UNITED_STATES:
        return _US_STATE_LOOKUP.get(text.lower(), text)
    return text


def normalize_industry(raw: str | None, mappings: Mapping[str, str] = STANDARD_INDUSTRY_MAP) -> str:
    """Map an industry wording to its NAICS sector name; missing becomes "Unknown" (D-070, D-076).

    Args:
        raw: The industry cell as received.
        mappings: Lowercase source wording to standard name; defaults to the starter map.
            Callers may pass the IndustryMapping table contents instead.

    Returns:
        The standard industry, the cleaned original when no mapping exists (so the value is
        kept and an admin can map it later), or UNKNOWN_INDUSTRY when the cell is empty.
    """
    text = _clean_text(raw)
    if text is None:
        return UNKNOWN_INDUSTRY
    return mappings.get(text.lower(), text)


def derive_company_name(email: str) -> str | None:
    """Derive a company name from a work-email domain, e.g. jane@acme-corp.com -> "Acme Corp".

    Used only when the file has no company name; the caller marks the result as derived
    (D-071). Callers must pass a work email: a free-mail domain would name the provider,
    not the company.

    Returns:
        The derived name, or None when the email is malformed.
    """
    domain = email_domain(email)
    if domain is None:
        return None
    labels = domain.split(".")
    # Country second-level suffixes (acme.co.uk) have two trailing labels, not one.
    suffix_length = 2 if ".".join(labels[-2:]) in SECOND_LEVEL_DOMAIN_SUFFIXES else 1
    name_labels = labels[:-suffix_length]
    if not name_labels:
        return None
    company_label = name_labels[-1]
    return " ".join(part.capitalize() for part in re.split(r"[-_]+", company_label) if part)


def normalize_linkedin_url(raw: str | None) -> str | None:
    """Reduce a LinkedIn profile link to a comparable form, e.g. "linkedin.com/in/jane-doe".

    "https://www.LinkedIn.com/in/Jane-Doe/?utm=x" and "linkedin.com/in/jane-doe" become the
    same text, so the third person-match clue (D-077) is not defeated by link decoration.

    Returns:
        The reduced link, or None when the cell is missing or blank.
    """
    text = _clean_text(raw)
    if text is None:
        return None
    text = _SCHEME_PREFIX.sub("", text.lower())
    text = re.split(r"[?#]", text, maxsplit=1)[0]
    text = text.removeprefix("www.").rstrip("/")
    return text or None


def normalize_company_name(raw: str | None) -> str | None:
    """Reduce a company name to the form stored in Company.normalized_name.

    Lowercases, drops punctuation and a trailing legal form: "Acme, Inc." and "ACME" both
    become "acme". Used as the last company-match clue (D-077).

    Returns:
        The reduced name, or None when nothing is left.
    """
    text = _clean_text(raw)
    if text is None:
        return None
    words = _NON_NAME_CHARACTERS.sub(" ", text.lower().replace("&", " and ")).split()
    while len(words) > 1 and words[-1] in _COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words) or None
