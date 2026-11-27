"""Tests for FilterSet validation: unknown fields, limits and contradictory combinations (M3-A2).

Needed because FilterSet is the single gate every search, segment and AI result passes through
(plan section 14 F): anything it accepts reaches the query, so every rejection rule is proven
here. No database is used.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.leads.filters import (
    MAX_TERM_LENGTH,
    MAX_VALUES_PER_LIST,
    SIZE_BAND_RANGES,
    FilterSet,
    SizeBand,
)
from app.leads.models import LeadStatusFlagType


def test_empty_filter_set_is_valid_and_applies_nothing() -> None:
    """No arguments: valid, every list empty, both toggles off (the default view)."""
    filters = FilterSet()

    assert filters.industries == [] and filters.uses_salesforce is None
    assert filters.eligible_only is False and filters.show_opted_out is False


def test_unknown_field_is_rejected() -> None:
    """A field FilterSet does not declare raises a validation error, never silently ignored."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FilterSet.model_validate({"industries": ["Banking"], "sql": "1=1"})


def test_terms_are_trimmed_and_empty_terms_rejected() -> None:
    """Whitespace is trimmed; an empty or blank term is an error, not dropped."""
    assert FilterSet(titles=["  CFO  "]).titles == ["CFO"]
    with pytest.raises(ValidationError):
        FilterSet(titles=["   "])


def test_list_and_term_length_limits() -> None:
    """More than MAX_VALUES_PER_LIST values or a term over MAX_TERM_LENGTH is rejected."""
    with pytest.raises(ValidationError):
        FilterSet(industries=["x"] * (MAX_VALUES_PER_LIST + 1))
    with pytest.raises(ValidationError):
        FilterSet(titles=["x" * (MAX_TERM_LENGTH + 1)])
    assert FilterSet(industries=["x"] * MAX_VALUES_PER_LIST)


def test_technologies_are_lowercased() -> None:
    """Technology tags are stored lowercase, so "Salesforce" is normalised to "salesforce"."""
    assert FilterSet(technologies=["Salesforce", " HubSpot "]).technologies == [
        "salesforce",
        "hubspot",
    ]


def test_revenue_min_above_max_is_rejected() -> None:
    """revenue_min greater than revenue_max fails; equal bounds and one-sided ranges pass."""
    with pytest.raises(ValidationError, match="revenue_min"):
        FilterSet(revenue_min=Decimal(10), revenue_max=Decimal(5))
    assert FilterSet(revenue_min=Decimal(5), revenue_max=Decimal(5))
    assert FilterSet(revenue_min=Decimal(5)).revenue_max is None


def test_negative_revenue_is_rejected() -> None:
    """Revenue cannot be negative (the column has the same check)."""
    with pytest.raises(ValidationError):
        FilterSet(revenue_min=Decimal(-1))


def test_flag_in_both_include_and_exclude_is_rejected() -> None:
    """A flag listed as included and excluded can never match, so it is rejected with its name."""
    with pytest.raises(ValidationError, match="partner"):
        FilterSet(
            flags_include=[LeadStatusFlagType.PARTNER],
            flags_exclude=[LeadStatusFlagType.PARTNER, LeadStatusFlagType.COMPETITOR],
        )
    assert FilterSet(
        flags_include=[LeadStatusFlagType.PARTNER], flags_exclude=[LeadStatusFlagType.COMPETITOR]
    )


def test_eligible_only_with_show_opted_out_is_rejected() -> None:
    """The two toggles contradict each other (an opted-out lead is never eligible): 422 rule."""
    with pytest.raises(ValidationError, match="cannot be used together"):
        FilterSet(eligible_only=True, show_opted_out=True)
    assert FilterSet(eligible_only=True).show_opted_out is False
    assert FilterSet(show_opted_out=True).eligible_only is False


def test_unknown_size_band_is_rejected() -> None:
    """Only smb, mid_market and enterprise are valid size bands."""
    with pytest.raises(ValidationError):
        FilterSet.model_validate({"size_bands": ["huge"]})


def test_size_band_ranges_follow_d085() -> None:
    """SMB 1-200, mid-market 201-1,000, enterprise above 1,000 with no upper limit (D-085)."""
    assert SIZE_BAND_RANGES[SizeBand.SMB] == (1, 200)
    assert SIZE_BAND_RANGES[SizeBand.MID_MARKET] == (201, 1000)
    assert SIZE_BAND_RANGES[SizeBand.ENTERPRISE] == (1001, None)
