"""Tests for the default view, "Show opted-out" and "Eligible only" on a real PostgreSQL (M3-A2).

Needed because the requirements fix what search shows by default (every lead except opted-out
ones, Q-LEADS-07, D-106, D-067) and "Eligible only" must agree with the eligibility service
(plan section 14 G). Each test builds synthetic leads and checks which ids appear.
"""

from datetime import timedelta

from factories.compliance import make_opt_out
from factories.leads import (
    make_duplicate_candidate,
    make_lead_status_flag,
    make_person,
    make_person_email,
    make_touch,
)
from factories.search import make_eligible_person
from sqlalchemy.orm import Session

from app.compliance.contracts import EligibilityReason
from app.compliance.eligibility import build_context, check_eligibility
from app.core.clock import now
from app.leads.filters import FilterSet
from app.leads.models import EmailType, LeadStatusFlagType, Person
from app.leads.search import search_leads

PAGE = 200


def _found(db: Session, **filters: object) -> set[object]:
    """Run a search with the given FilterSet fields and return the matching person ids."""
    response = search_leads(db, FilterSet(**filters), limit=PAGE, offset=0)
    return {row.person_id for row in response.items}


def _opted_out_person(db: Session) -> Person:
    """An otherwise eligible person whose address has an active opt-out."""
    person = make_eligible_person(db)
    address = make_person_email(db, person=person).normalized_address
    make_opt_out(db, email_normalized=address)
    return person


def test_default_view_hides_opted_out_leads(db_session: Session) -> None:
    """With no filters, an opted-out lead is hidden and a normal lead is shown."""
    visible = make_eligible_person(db_session)
    hidden = _opted_out_person(db_session)

    result = _found(db_session)

    assert visible.id in result and hidden.id not in result


def test_show_opted_out_adds_them_to_the_list(db_session: Session) -> None:
    """show_opted_out adds opted-out leads (decision 12a): everyone else stays in the list."""
    visible = make_eligible_person(db_session)
    opted_out = _opted_out_person(db_session)

    result = _found(db_session, show_opted_out=True)

    assert {visible.id, opted_out.id} <= result


def test_removed_opt_out_is_visible_again(db_session: Session) -> None:
    """An opt-out that was removed (removed_at set) no longer hides the lead."""
    person = make_eligible_person(db_session)
    address = make_person_email(db_session, person=person).normalized_address
    make_opt_out(db_session, email_normalized=address, removed_at=now(), removal_reason="test")

    assert person.id in _found(db_session)


def test_opt_out_on_any_address_hides_the_lead(db_session: Session) -> None:
    """An opt-out on a secondary address hides the lead too (opted out means any address)."""
    person = make_eligible_person(db_session)
    second = make_person_email(db_session, person=person, type=EmailType.PERSONAL)
    make_opt_out(db_session, email_normalized=second.normalized_address)

    assert person.id not in _found(db_session)


def test_default_view_keeps_leads_that_are_ineligible_for_other_reasons(
    db_session: Session,
) -> None:
    """Replied, cooling-off or duplicate leads still appear by default (they only get badges)."""
    replied = make_eligible_person(db_session, replied_at=now())
    cooling = make_eligible_person(db_session, last_contacted_at=now() - timedelta(days=1))
    no_email = make_person(db_session)

    assert {replied.id, cooling.id, no_email.id} <= _found(db_session)


def test_eligible_only_excludes_every_blocking_reason(db_session: Session) -> None:
    """eligible_only keeps the clean lead and drops one lead per eligibility reason."""
    clean = make_eligible_person(db_session)
    blocked = {
        EligibilityReason.OPTED_OUT: _opted_out_person(db_session),
        EligibilityReason.NO_USABLE_EMAIL: make_person(db_session),
        EligibilityReason.REPLIED: make_eligible_person(db_session, replied_at=now()),
        EligibilityReason.COOLING_OFF: make_eligible_person(
            db_session, last_contacted_at=now() - timedelta(days=1)
        ),
    }
    flagged = make_eligible_person(db_session)
    make_lead_status_flag(db_session, person=flagged, flag_type=LeadStatusFlagType.QUALIFIED)
    blocked[EligibilityReason.QUALIFIED_OR_HANDED_OFF] = flagged
    limit = make_eligible_person(db_session)
    for _ in range(3):
        make_touch(db_session, person=limit, occurred_at=now() - timedelta(days=2))
    blocked[EligibilityReason.CONTACT_LIMIT] = limit
    duplicate_pair = make_duplicate_candidate(db_session)
    blocked[EligibilityReason.POSSIBLE_DUPLICATE] = db_session.get(
        Person, duplicate_pair.person_a_id
    )

    result = _found(db_session, eligible_only=True)

    assert clean.id in result
    for reason, person in blocked.items():
        assert person.id not in result, reason


def test_eligible_only_agrees_with_check_eligibility(db_session: Session) -> None:
    """An eligible_only search returns exactly the leads the per-person check calls eligible."""
    people = [
        make_eligible_person(db_session),
        make_eligible_person(db_session, replied_at=now()),
        make_person(db_session),
        _opted_out_person(db_session),
        make_eligible_person(db_session, last_contacted_at=now() - timedelta(days=500)),
    ]
    ctx = build_context(db_session)
    expected = {p.id for p in people if check_eligibility(db_session, p, ctx).eligible}

    result = _found(db_session, eligible_only=True)

    assert result & {p.id for p in people} == expected
