"""Tests for result-row contents and badges on a real PostgreSQL (M3-A2).

Needed because the default view must label leads with cooling-off, replied, possible duplicate,
unverified email and opted out (Q-LEADS-07, D-067, D-106), and rows carry the company, primary
email, owner and flags the screen shows (m3.md decision 13). Synthetic leads, one fact each.
"""

from datetime import timedelta

from factories.compliance import make_opt_out
from factories.core import make_user
from factories.leads import (
    make_company,
    make_duplicate_candidate,
    make_lead_status_flag,
    make_person,
    make_person_email,
)
from factories.search import make_eligible_person
from sqlalchemy.orm import Session

from app.core.clock import now
from app.leads.filters import FilterSet
from app.leads.models import EmailVerificationStatus, LeadStatusFlagType, Person
from app.leads.search import search_leads
from app.leads.search_schemas import Badge, SearchRow


def _row(db: Session, person: Person) -> SearchRow:
    """Search with the opted-out leads shown and return the row of this person."""
    response = search_leads(db, FilterSet(show_opted_out=True), limit=200, offset=0)
    return next(row for row in response.items if row.person_id == person.id)


def test_clean_lead_has_no_badges(db_session: Session) -> None:
    """A verified, uncontacted lead with nothing wrong carries no badge."""
    person = make_eligible_person(db_session)

    assert _row(db_session, person).badges == []


def test_each_badge_appears_on_its_trigger(db_session: Session) -> None:
    """One lead per badge: replied, cooling off, possible duplicate, unverified, opted out."""
    replied = make_eligible_person(db_session, replied_at=now())
    cooling = make_eligible_person(db_session, last_contacted_at=now() - timedelta(days=5))
    duplicate = db_session.get(Person, make_duplicate_candidate(db_session).person_a_id)
    unverified = make_person(db_session)
    make_person_email(
        db_session, person=unverified, verification_status=EmailVerificationStatus.UNVERIFIED
    )
    opted_out = make_eligible_person(db_session)
    address = make_person_email(db_session, person=opted_out).normalized_address
    make_opt_out(db_session, email_normalized=address)

    assert _row(db_session, replied).badges == [Badge.REPLIED]
    assert _row(db_session, cooling).badges == [Badge.COOLING_OFF]
    assert Badge.POSSIBLE_DUPLICATE in _row(db_session, duplicate).badges
    assert _row(db_session, unverified).badges == [Badge.UNVERIFIED_EMAIL]
    assert Badge.OPTED_OUT in _row(db_session, opted_out).badges


def test_a_lead_can_carry_several_badges_in_a_fixed_order(db_session: Session) -> None:
    """Replied and cooling off together: both badges, in the declared Badge order."""
    person = make_eligible_person(
        db_session, replied_at=now(), last_contacted_at=now() - timedelta(days=2)
    )

    assert _row(db_session, person).badges == [Badge.COOLING_OFF, Badge.REPLIED]


def test_flags_without_a_badge_are_listed_on_the_row(db_session: Session) -> None:
    """Status flags are returned as flags; Qualified is not one of the five badges."""
    person = make_eligible_person(db_session)
    make_lead_status_flag(db_session, person=person, flag_type=LeadStatusFlagType.QUALIFIED)
    make_lead_status_flag(db_session, person=person, flag_type=LeadStatusFlagType.PARTNER)

    row = _row(db_session, person)

    assert set(row.flags) == {LeadStatusFlagType.QUALIFIED, LeadStatusFlagType.PARTNER}
    assert row.badges == []


def test_row_carries_company_owner_and_primary_email(db_session: Session) -> None:
    """The row shows the company facts, the owner's display name and only the primary address."""
    owner = make_user(db_session)
    company = make_company(db_session, industry="Banking", employee_count=250, hq_state="Kerala")
    person = make_person(db_session, company_id=company.id, owner_id=owner.id, title="CFO")
    make_person_email(
        db_session,
        person=person,
        address="primary@acme.example",
        verification_status=EmailVerificationStatus.VERIFIED,
        is_primary=True,
    )
    make_person_email(db_session, person=person, address="other@acme.example")

    row = _row(db_session, person)

    assert row.company is not None and row.company.name == company.name
    assert (row.company.industry, row.company.employee_count) == ("Banking", 250)
    assert row.company.hq_state == "Kerala"
    assert row.owner is not None and row.owner.id == owner.id and row.owner.name == owner.email
    assert row.primary_email is not None
    assert row.primary_email.address == "primary@acme.example"
    assert row.primary_email.verification_status is EmailVerificationStatus.VERIFIED


def test_lead_without_company_owner_or_primary_email(db_session: Session) -> None:
    """Missing company, owner and primary address come back as null, not as an error."""
    person = make_person(db_session)

    row = _row(db_session, person)

    assert row.company is None and row.owner is None and row.primary_email is None
    assert row.flags == []
