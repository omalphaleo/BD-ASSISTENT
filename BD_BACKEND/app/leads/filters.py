"""The one definition of a lead search filter (FilterSet) and its validation rules (M3-A2).

Needed because the search form, saved segments, CSV export and AI natural-language search must
all describe "which leads" the same way (plan section 14 F, [AGREED]). search.py builds its
query only from these fields, so a field that is not declared here can never reach the database:
unknown fields are rejected, never ignored.
"""

import enum
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.leads.models import LeadStatusFlagType

# Limits that keep a request small and a query predictable. Over the limit is a 422.
MAX_VALUES_PER_LIST = 50
MAX_TERM_LENGTH = 100

# Employee-count bands (D-085): SMB 1-200, mid-market 201-1,000, enterprise above 1,000.
SMB_MAX_EMPLOYEES = 200
MID_MARKET_MAX_EMPLOYEES = 1_000


class SizeBand(enum.StrEnum):
    """Company size profile by employee count (D-085)."""

    SMB = "smb"
    MID_MARKET = "mid_market"
    ENTERPRISE = "enterprise"


# Inclusive (low, high) employee counts per band; None means no upper limit. A company with no
# employee count, or a count of 0, belongs to no band, so a size filter never matches it.
SIZE_BAND_RANGES: dict[SizeBand, tuple[int, int | None]] = {
    SizeBand.SMB: (1, SMB_MAX_EMPLOYEES),
    SizeBand.MID_MARKET: (SMB_MAX_EMPLOYEES + 1, MID_MARKET_MAX_EMPLOYEES),
    SizeBand.ENTERPRISE: (MID_MARKET_MAX_EMPLOYEES + 1, None),
}


class SortField(enum.StrEnum):
    """Columns a search can be ordered by. A fixed list, so no arbitrary column is reachable."""

    NAME = "name"  # last name, then first name
    COMPANY = "company"  # company name
    TITLE = "title"
    LAST_CONTACTED_AT = "last_contacted_at"
    CREATED_AT = "created_at"


class SortDirection(enum.StrEnum):
    """Ascending or descending order."""

    ASC = "asc"
    DESC = "desc"


# A trimmed, non-empty, length-limited term; empty strings are rejected, not silently dropped.
Term = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TERM_LENGTH)
]
TermList = Annotated[list[Term], Field(max_length=MAX_VALUES_PER_LIST)]


class FilterSet(BaseModel):
    """Every way a lead search can be narrowed.

    Different filters combine with AND; the values inside one list combine with OR. A filter
    left at its default (an empty list or None) is not applied. Matching rules:

    - industries, countries, states, cities, funding_stages: exact, case-insensitive.
    - countries, states, cities match the person's own location OR the company headquarters.
    - titles, company_names: "contains", case-insensitive.
    - technologies: exact tag match on the lowercased technology list.
    - size_bands: employee count inside any chosen band (D-085).
    - revenue_min / revenue_max: inclusive, in the currency the source used (not recorded).

    Unknown fields raise a validation error (extra="forbid").
    """

    model_config = ConfigDict(extra="forbid")

    industries: TermList = []
    company_names: TermList = []
    size_bands: Annotated[list[SizeBand], Field(max_length=len(SizeBand))] = []
    countries: TermList = []
    states: TermList = []
    cities: TermList = []
    titles: TermList = []
    technologies: TermList = []
    uses_salesforce: bool | None = None
    revenue_min: Annotated[Decimal | None, Field(ge=0)] = None
    revenue_max: Annotated[Decimal | None, Field(ge=0)] = None
    funding_stages: TermList = []
    # A lead matches "include" when it carries at least one of these flags and "exclude" when
    # it carries none of them (D-065: BD filters on flags instead of a suppression list).
    flags_include: Annotated[
        list[LeadStatusFlagType], Field(max_length=len(LeadStatusFlagType))
    ] = []
    flags_exclude: Annotated[
        list[LeadStatusFlagType], Field(max_length=len(LeadStatusFlagType))
    ] = []
    # Off by default: the default view shows every lead except opted-out ones (D-106, D-067).
    eligible_only: bool = False
    show_opted_out: bool = False

    @model_validator(mode="after")
    def _check_combinations(self) -> Self:
        """Reject filter combinations that can never make sense.

        Raises:
            ValueError: revenue_min above revenue_max; a flag both included and excluded; or
                eligible_only together with show_opted_out (an opted-out lead is never
                eligible, so the two contradict each other).
        """
        if (
            self.revenue_min is not None
            and self.revenue_max is not None
            and self.revenue_min > self.revenue_max
        ):
            raise ValueError("revenue_min must not be greater than revenue_max")
        both = set(self.flags_include) & set(self.flags_exclude)
        if both:
            names = ", ".join(sorted(flag.value for flag in both))
            raise ValueError(f"a flag cannot be both included and excluded: {names}")
        if self.eligible_only and self.show_opted_out:
            raise ValueError("eligible_only and show_opted_out cannot be used together")
        return self

    @model_validator(mode="after")
    def _lowercase_technologies(self) -> Self:
        """Store technologies lowercased, the form the companies table keeps them in."""
        self.technologies = [tag.lower() for tag in self.technologies]
        return self
