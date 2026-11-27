"""Tests for each search filter alone and in combination, on a real PostgreSQL (M3-A2).

Needed because search builds its SQL only from FilterSet fields (plan section 14 F): every
filter must match what the requirements say (D-025, D-063, D-085) and nothing more. Each test
builds a few synthetic leads, runs one search through search_leads() and compares the set of
matching person ids.
"""

from decimal import Decimal

from factories.leads import make_company, make_lead_status_flag, make_person
from sqlalchemy.orm import Session

from app.leads.filters import FilterSet
from app.leads.models import LeadStatusFlagType, Person
from app.leads.search import search_leads

PAGE = 200


def _found(db: Session, **filters: object) -> set[object]:
    """Run a search with the given FilterSet fields and return the matching person ids."""
    response = search_leads(db, FilterSet(**filters), limit=PAGE, offset=0)
    return {row.person_id for row in response.items}


def _lead(db: Session, company_fields: dict[str, object] | None = None, **person: object) -> Person:
    """A lead at a new company built from company_fields (no company when it is None)."""
    company = make_company(db, **company_fields) if company_fields is not None else None
    return make_person(db, company_id=company.id if company else None, **person)


def test_no_filters_returns_every_lead(db_session: Session) -> None:
    """An empty FilterSet applies nothing: all leads (here without opt-outs) are returned."""
    first, second = _lead(db_session), _lead(db_session, {"industry": "Banking"})

    assert {first.id, second.id} <= _found(db_session)


def test_industries_match_exactly_ignoring_case(db_session: Session) -> None:
    """Industry is an exact, case-insensitive match; "Bank" does not match "Banking"."""
    bank = _lead(db_session, {"industry": "Banking"})
    other = _lead(db_session, {"industry": "Healthcare"})

    assert _found(db_session, industries=["banking"]) & {bank.id, other.id} == {bank.id}
    assert bank.id not in _found(db_session, industries=["Bank"])


def test_company_names_match_by_contains(db_session: Session) -> None:
    """Company name is a case-blind contains match; a wildcard the user types is literal."""
    acme = _lead(db_session, {"name": "Acme Holdings"})
    percent = _lead(db_session, {"name": "100% Pure"})
    other = _lead(db_session, {"name": "Globex"})
    created = {acme.id, percent.id, other.id}

    assert _found(db_session, company_names=["acme"]) & created == {acme.id}
    assert _found(db_session, company_names=["100%"]) & created == {percent.id}
    # A bare "%" would match everything if it were not escaped; only the "100% Pure" has one.
    assert _found(db_session, company_names=["%"]) & created == {percent.id}


def test_size_bands_use_d085_boundaries(db_session: Session) -> None:
    """200 is SMB, 201 mid-market, 1,000 mid-market, 1,001 enterprise; 0 and unknown match none."""
    sizes = {n: _lead(db_session, {"employee_count": n}) for n in (1, 200, 201, 1000, 1001, 0)}
    unknown = _lead(db_session, {"employee_count": None})
    no_company = _lead(db_session)
    created = {p.id for p in sizes.values()} | {unknown.id, no_company.id}

    assert _found(db_session, size_bands=["smb"]) & created == {sizes[1].id, sizes[200].id}
    assert _found(db_session, size_bands=["mid_market"]) & created == {
        sizes[201].id,
        sizes[1000].id,
    }
    assert _found(db_session, size_bands=["enterprise"]) & created == {sizes[1001].id}
    both = _found(db_session, size_bands=["smb", "enterprise"]) & created
    assert both == {sizes[1].id, sizes[200].id, sizes[1001].id}


def test_location_matches_person_or_company_headquarters(db_session: Session) -> None:
    """A state/country/city value matches the person's own place OR the company HQ, exactly."""
    by_person = _lead(db_session, state="Karnataka", city="Bengaluru", country="India")
    by_company = _lead(
        db_session, {"hq_state": "karnataka", "hq_city": "Mysuru", "hq_country": "India"}
    )
    elsewhere = _lead(db_session, {"hq_state": "Kerala", "hq_country": "India"}, state="Kerala")
    created = {by_person.id, by_company.id, elsewhere.id}

    assert _found(db_session, states=["Karnataka"]) & created == {by_person.id, by_company.id}
    assert _found(db_session, cities=["Mysuru"]) & created == {by_company.id}
    assert _found(db_session, countries=["india"]) & created == created
    # Exact, not contains: "Kar" is not Karnataka.
    assert _found(db_session, states=["Kar"]) & created == set()


def test_titles_match_by_contains_with_any_term(db_session: Session) -> None:
    """Titles match case-insensitively by contains, and any one of several terms is enough."""
    cfo = _lead(db_session, title="Group CFO")
    chief = _lead(db_session, title="Chief Financial Officer")
    cto = _lead(db_session, title="CTO")
    untitled = _lead(db_session, title=None)
    created = {cfo.id, chief.id, cto.id, untitled.id}

    assert _found(db_session, titles=["cfo"]) & created == {cfo.id}
    assert _found(db_session, titles=["cfo", "chief financial"]) & created == {cfo.id, chief.id}


def test_technologies_match_any_exact_tag(db_session: Session) -> None:
    """A technology filter matches companies having any chosen tag, exactly (no partial tags)."""
    sf = _lead(db_session, {"technologies": ["salesforce", "aws"]})
    hub = _lead(db_session, {"technologies": ["hubspot"]})
    none = _lead(db_session, {"technologies": []})
    created = {sf.id, hub.id, none.id}

    assert _found(db_session, technologies=["Salesforce"]) & created == {sf.id}
    assert _found(db_session, technologies=["aws", "hubspot"]) & created == {sf.id, hub.id}
    assert _found(db_session, technologies=["sales"]) & created == set()


def test_uses_salesforce_true_and_false(db_session: Session) -> None:
    """True finds Salesforce users, False those who do not; no company matches neither."""
    yes = _lead(db_session, {"uses_salesforce": True})
    no = _lead(db_session, {"uses_salesforce": False})
    nobody = _lead(db_session)
    created = {yes.id, no.id, nobody.id}

    assert _found(db_session, uses_salesforce=True) & created == {yes.id}
    assert _found(db_session, uses_salesforce=False) & created == {no.id}


def test_revenue_range_is_inclusive_and_excludes_unknown(db_session: Session) -> None:
    """revenue_min/max include their own value; a company with no revenue never matches."""
    low = _lead(db_session, {"annual_revenue": Decimal(100)})
    mid = _lead(db_session, {"annual_revenue": Decimal(500)})
    high = _lead(db_session, {"annual_revenue": Decimal(1000)})
    unknown = _lead(db_session, {"annual_revenue": None})
    created = {low.id, mid.id, high.id, unknown.id}

    assert _found(db_session, revenue_min=Decimal(500)) & created == {mid.id, high.id}
    assert _found(db_session, revenue_max=Decimal(500)) & created == {low.id, mid.id}
    assert _found(db_session, revenue_min=Decimal(100), revenue_max=Decimal(100)) & created == {
        low.id
    }


def test_funding_stage_uses_latest_funding_round_type(db_session: Session) -> None:
    """The funding-stage filter reads latest_funding_round_type (Q-LEADS-05), exact, case-blind."""
    seed = _lead(db_session, {"latest_funding_round_type": "Seed"})
    series_a = _lead(db_session, {"latest_funding_round_type": "Series A"})
    # funding_stage alone is not what the filter reads.
    stage_only = _lead(db_session, {"funding_stage": "Seed"})
    created = {seed.id, series_a.id, stage_only.id}

    assert _found(db_session, funding_stages=["seed"]) & created == {seed.id}
    assert _found(db_session, funding_stages=["Seed", "Series A"]) & created == {
        seed.id,
        series_a.id,
    }


def test_flags_include_and_exclude(db_session: Session) -> None:
    """flags_include needs any of the flags; flags_exclude removes anyone carrying one (D-065)."""
    partner = _lead(db_session)
    competitor = _lead(db_session)
    plain = _lead(db_session)
    make_lead_status_flag(db_session, person=partner, flag_type=LeadStatusFlagType.PARTNER)
    make_lead_status_flag(db_session, person=competitor, flag_type=LeadStatusFlagType.COMPETITOR)
    created = {partner.id, competitor.id, plain.id}

    assert _found(db_session, flags_include=["partner"]) & created == {partner.id}
    assert _found(db_session, flags_include=["partner", "competitor"]) & created == {
        partner.id,
        competitor.id,
    }
    assert _found(db_session, flags_exclude=["competitor"]) & created == {partner.id, plain.id}


def test_different_filters_combine_with_and(db_session: Session) -> None:
    """Industry AND state AND title must all hold; values inside one list are OR."""
    match = _lead(db_session, {"industry": "Banking", "hq_state": "Karnataka"}, title="CFO")
    wrong_title = _lead(
        db_session, {"industry": "Banking", "hq_state": "Karnataka"}, title="Engineer"
    )
    wrong_state = _lead(db_session, {"industry": "Banking", "hq_state": "Kerala"}, title="CFO")
    created = {match.id, wrong_title.id, wrong_state.id}

    result = _found(db_session, industries=["Banking"], states=["Karnataka"], titles=["cfo"])
    assert result & created == {match.id}
    either_state = _found(db_session, industries=["Banking"], states=["Karnataka", "Kerala"])
    assert either_state & created == created


def test_filters_that_match_nothing_return_empty_page(db_session: Session) -> None:
    """A filter no lead satisfies gives an empty page with total 0, not an error."""
    _lead(db_session, {"industry": "Banking"})

    response = search_leads(
        db_session, FilterSet(industries=["No Such Industry"]), limit=PAGE, offset=0
    )

    assert response.items == [] and response.total == 0
