"""Turns a mapped import row into typed, normalized person and company values (M2-B4).

Needed because merge and create must work from clean values, not raw cells: numbers parsed,
names, places and domains normalized, engagement flags read as yes/no. Keeping this apart from
ingest.py means the one place that knows the app field names (an assumption until the
column-mapping task M2-A2 fixes them) is small and tested. Pure functions: no database, no
clock, and a cell that cannot be read becomes None instead of raising, so one bad cell never
fails a row (D-068).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.leads.contracts import JsonScalar, SourceRow
from app.leads.engagement import EngagementHistory
from app.leads.normalization import (
    normalize_country,
    normalize_domain,
    normalize_industry,
    normalize_linkedin_url,
    normalize_name,
    normalize_state,
)
from app.leads.quarantine import EMAIL_FIELDS, EMAIL_STATUS_FIELD, FIRST_NAME_FIELD

LAST_NAME_FIELD = "last_name"
COMPANY_NAME_FIELD = "company_name"
COMPANY_WEBSITE_FIELD = "company_website"
SALESFORCE_TECHNOLOGY = "salesforce"
_TRUE_WORDS = frozenset({"true", "yes", "y", "1", "x"})
# Apollo wording of the email status that means the address bounced.
_BOUNCED_STATUS = "bounced"

Values = Mapping[str, JsonScalar]


@dataclass(frozen=True, slots=True)
class ParsedRow:
    """The values of one row, ready for validation, matching and merge.

    Attributes:
        first_name_cell: First-name cell as received (validation normalizes it).
        email_cells: The email cells in priority order, as received.
        email_status: The source's email verification wording, as received.
        last_name: Normalized last name.
        person: Person columns to create or merge (blank values already dropped).
        company: Company columns to create or merge (blank values already dropped).
        company_name: Normalized-for-display company name from the file, or None.
        website_domain: Domain of the company website cell, the fallback clue (D-077).
        engagement: What the file says about earlier contact (D-073).
    """

    first_name_cell: str | None
    email_cells: tuple[str | None, ...]
    email_status: str | None
    last_name: str | None
    person: dict[str, object]
    company: dict[str, object]
    company_name: str | None
    website_domain: str | None
    engagement: EngagementHistory


def _text(values: Values, key: str) -> str | None:
    """Return a cell as trimmed text, or None when missing or blank."""
    value = values.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _integer(values: Values, key: str) -> int | None:
    """Return a whole number from a cell such as 250, "250" or "1,200"; else None."""
    text = _text(values, key)
    if text is None:
        return None
    try:
        return int(Decimal(text.replace(",", "")))
    except (InvalidOperation, ValueError):
        return None


def _money(values: Values, key: str) -> Decimal | None:
    """Return an amount from a cell such as 1500000 or "1,500,000.50"; else None."""
    text = _text(values, key)
    if text is None:
        return None
    try:
        return Decimal(text.replace(",", "").lstrip("$"))
    except InvalidOperation:
        return None


def _flag(values: Values, key: str) -> bool:
    """Read a yes/no cell: true, yes, y, 1 and x mean yes; anything else, or blank, means no."""
    value = values.get(key)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE_WORDS if value is not None else False


def _moment(values: Values, key: str) -> datetime | None:
    """Read an ISO date or date-time cell as an aware UTC time; None when unreadable."""
    text = _text(values, key)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _tags(values: Values, key: str) -> list[str] | None:
    """Split a comma-separated cell into tags (technologies, keywords); None when blank."""
    text = _text(values, key)
    if text is None:
        return None
    tags = [part.strip() for part in text.split(",") if part.strip()]
    return tags or None


def _present(items: Mapping[str, object]) -> dict[str, object]:
    """Drop None values so a missing cell is never treated as a value to write."""
    return {key: value for key, value in items.items() if value is not None}


def email_cells(row: SourceRow) -> tuple[str | None, ...]:
    """Return the row's email cells in priority order, the raw text standing in for a blank one."""
    cells = [_text(row.values, field) for field in EMAIL_FIELDS]
    if cells[0] is None:
        cells[0] = row.raw_email
    return tuple(cells)


def parse_row(row: SourceRow) -> ParsedRow:
    """Read and normalize every value of a mapped row.

    The field names read here are an assumption until M2-A2 fixes the app field names
    (m2.md section 31); the quarantine editor uses the same names.
    """
    values = row.values
    country = normalize_country(_text(values, "country")) or normalize_country(row.default_country)
    technologies = _tags(values, "technologies")
    hq_country = normalize_country(_text(values, "hq_country"))
    person = _present(
        {
            "source_record_id": _text(values, "source_record_id"),
            "linkedin_url": normalize_linkedin_url(_text(values, "linkedin_url")),
            "title": _text(values, "title"),
            "seniority": _text(values, "seniority"),
            "department": _text(values, "department"),
            "city": _text(values, "city"),
            "state": normalize_state(_text(values, "state"), country),
            "country": country,
            "source_status": _text(values, "source_status"),
            "source_stage": _text(values, "source_stage"),
        }
    )
    company = _present(
        {
            "apollo_account_id": _text(values, "apollo_account_id"),
            "naics": _text(values, "naics"),
            "sic": _text(values, "sic"),
            "employee_count": _integer(values, "employee_count"),
            "annual_revenue": _money(values, "annual_revenue"),
            "funding_stage": _text(values, "funding_stage"),
            "latest_funding_round_type": _text(values, "latest_funding_round_type"),
            "total_funding": _money(values, "total_funding"),
            "technologies": technologies,
            "keywords": _tags(values, "keywords"),
            "hq_city": _text(values, "hq_city"),
            "hq_state": normalize_state(_text(values, "hq_state"), hq_country),
            "hq_country": hq_country,
            "founded_year": _integer(values, "founded_year"),
        }
    )
    if technologies is not None:
        # Derived from the technologies list (companies table note); only set when it is known.
        company["uses_salesforce"] = any(
            tag.lower() == SALESFORCE_TECHNOLOGY for tag in technologies
        )
    industry_cell = _text(values, "industry")
    if industry_cell is not None:
        # A missing industry is not written: the "Unknown" default (D-070) applies on create only.
        company["industry"] = normalize_industry(industry_cell)

    email_status = _text(values, EMAIL_STATUS_FIELD)
    engagement = EngagementHistory(
        do_not_contact=_flag(values, "do_not_contact"),
        bounced=_flag(values, "email_bounced") or (email_status or "").lower() == _BOUNCED_STATUS,
        replied=_flag(values, "replied"),
        replied_at=_moment(values, "replied_at"),
        last_contacted_at=_moment(values, "last_contacted_at"),
    )
    return ParsedRow(
        first_name_cell=_text(values, FIRST_NAME_FIELD),
        email_cells=email_cells(row),
        email_status=email_status,
        last_name=normalize_name(_text(values, LAST_NAME_FIELD)),
        person=person,
        company=company,
        company_name=_text(values, COMPANY_NAME_FIELD),
        website_domain=normalize_domain(_text(values, COMPANY_WEBSITE_FIELD)),
        engagement=engagement,
    )
