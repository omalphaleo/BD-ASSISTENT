"""Request and response shapes of lead search (M3-A2).

Needed so the search endpoint, the generated frontend client and later tasks (segments,
export, NL search) agree on one contract. Pydantic v2 models only; no logic lives here.
Contact detail is limited to the primary email address: phones and the other addresses stay
on the lead page (m3.md decision 13).
"""

import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.leads.filters import FilterSet, SizeBand, SortDirection, SortField
from app.leads.models import EmailVerificationStatus, LeadStatusFlagType

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class Badge(enum.StrEnum):
    """Labels shown on a result row. The five approved ones (Q-LEADS-07, D-067, D-106)."""

    COOLING_OFF = "cooling_off"
    REPLIED = "replied"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    UNVERIFIED_EMAIL = "unverified_email"
    OPTED_OUT = "opted_out"


class SearchRequest(BaseModel):
    """One search: the filters, the order and the page wanted."""

    model_config = ConfigDict(extra="forbid")

    filters: FilterSet = Field(default_factory=FilterSet)
    sort: SortField = SortField.NAME
    direction: SortDirection = SortDirection.ASC
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0)


class CompanySummary(BaseModel):
    """The company facts a result row shows."""

    id: uuid.UUID
    name: str
    industry: str
    employee_count: int | None
    hq_city: str | None
    hq_state: str | None
    hq_country: str | None


class OwnerSummary(BaseModel):
    """The rep who owns the lead; the user's sign-in email is the only display name stored."""

    id: uuid.UUID
    name: str


class PrimaryEmail(BaseModel):
    """The lead's primary address and whether the source verified it (D-042)."""

    address: str
    verification_status: EmailVerificationStatus


class SearchRow(BaseModel):
    """One lead in the results."""

    person_id: uuid.UUID
    first_name: str
    last_name: str | None
    title: str | None
    seniority: str | None
    city: str | None
    state: str | None
    country: str | None
    company: CompanySummary | None
    primary_email: PrimaryEmail | None
    owner: OwnerSummary | None
    last_contacted_at: datetime | None
    flags: list[LeadStatusFlagType]
    badges: list[Badge]


class SearchResponse(BaseModel):
    """A page of results. `total` counts every lead matching the filters, not only this page,
    so "select all matching" can show its count without a second endpoint."""

    items: list[SearchRow]
    total: int
    limit: int
    offset: int


class FilterOptionsResponse(BaseModel):
    """The values the filter checkboxes offer, read from the data.

    Each list is capped; a name in `truncated` means that list was cut off.
    """

    industries: list[str]
    countries: list[str]
    states: list[str]
    cities: list[str]
    funding_stages: list[str]
    technologies: list[str]
    size_bands: list[SizeBand]
    flags: list[LeadStatusFlagType]
    truncated: list[str]
