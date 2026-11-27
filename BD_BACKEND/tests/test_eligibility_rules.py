"""Tests for each rule of the eligibility service in app.compliance.eligibility (M3-A1).

Needed because the eligibility rules decide who may be emailed, so every reason code, the
non-blocking warnings and each time boundary needs its own test. Uses real PostgreSQL and
synthetic leads; the clock is a fixed EligibilityContext, never the real time.
"""

from datetime import UTC, datetime, timedelta

from factories.compliance import make_opt_out
from factories.leads import (
    make_duplicate_candidate,
    make_lead_status_flag,
    make_person,
    make_person_email,
    make_touch,
)
from factories.search import make_eligible_person
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.contracts import (
    EligibilityContext,
    EligibilityReason,
    EligibilityWarning,
)
from app.compliance.eligibility import (
    build_context,
    check_eligibility,
    eligible_person_ids,
    eligible_queryset,
)
from app.leads.models import (
    DuplicateStatus,
    EmailType,
    LeadStatusFlagType,
    PersonEmail,
    TouchDirection,
    TouchStatus,
)

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
CTX = EligibilityContext(now=NOW, cooling_off_days=90)


def _reasons(db: Session, person: object) -> tuple[EligibilityReason, ...]:
    """The blocking reasons of a person under the fixed test context."""
    return check_eligibility(db, person, CTX).reasons  # type: ignore[arg-type]


def test_clean_lead_is_eligible(db_session: Session) -> None:
    """A lead with a verified work address and no other facts has no reason and no warning."""
    person = make_eligible_person(db_session)

    result = check_eligibility(db_session, person, CTX)

    assert result.eligible
    assert result.reasons == () and result.warnings == ()


def test_active_opt_out_on_any_address_blocks(db_session: Session) -> None:
    """An active opt-out on a second (personal) address still gives opted_out (decision 2)."""
    person = make_eligible_person(db_session)
    make_person_email(
        db_session, person=person, normalized_address="me@home.example", type=EmailType.PERSONAL
    )
    make_opt_out(db_session, email_normalized="me@home.example")

    assert _reasons(db_session, person) == (EligibilityReason.OPTED_OUT,)


def test_removed_opt_out_does_not_block(db_session: Session) -> None:
    """A removed opt-out (removed_at set with a reason) no longer blocks the person."""
    person = make_eligible_person(db_session)
    address = "gone@acme.example"
    make_person_email(db_session, person=person, normalized_address=address)
    make_opt_out(
        db_session,
        email_normalized=address,
        removed_at=NOW,
        removal_reason="Asked to be contacted again",
    )

    assert _reasons(db_session, person) == ()


def test_no_usable_email_when_only_invalid_personal_or_generic(db_session: Session) -> None:
    """Bounced, personal and generic addresses are never usable (D-072, D-073)."""
    person = make_person(db_session)
    make_person_email(db_session, person=person, normalized_address="a@x.example", is_invalid=True)
    make_person_email(
        db_session, person=person, normalized_address="b@x.example", type=EmailType.PERSONAL
    )
    make_person_email(
        db_session, person=person, normalized_address="c@x.example", type=EmailType.GENERIC
    )

    assert _reasons(db_session, person) == (EligibilityReason.NO_USABLE_EMAIL,)


def test_person_without_any_email_has_no_usable_email(db_session: Session) -> None:
    """A person with no address at all is blocked by no_usable_email."""
    assert _reasons(db_session, make_person(db_session)) == (EligibilityReason.NO_USABLE_EMAIL,)


def test_replied_blocks(db_session: Session) -> None:
    """A person who replied gets the replied reason (D-082)."""
    person = make_eligible_person(db_session, replied_at=NOW - timedelta(days=200))

    assert _reasons(db_session, person) == (EligibilityReason.REPLIED,)


def test_qualified_and_handed_off_block_other_flags_do_not(db_session: Session) -> None:
    """Qualified and Handed Off block (D-101); the other four flags do not (D-065)."""
    blocked = make_eligible_person(db_session)
    make_lead_status_flag(db_session, person=blocked, flag_type=LeadStatusFlagType.QUALIFIED)
    handed_off = make_eligible_person(db_session)
    make_lead_status_flag(
        db_session, person=handed_off, flag_type=LeadStatusFlagType.HANDED_OFF_TO_SALES
    )
    free = make_eligible_person(db_session)
    for flag in (
        LeadStatusFlagType.EXISTING_CUSTOMER,
        LeadStatusFlagType.PARTNER,
        LeadStatusFlagType.COMPETITOR,
        LeadStatusFlagType.IN_CONVERSATION,
    ):
        make_lead_status_flag(db_session, person=free, flag_type=flag)

    assert _reasons(db_session, blocked) == (EligibilityReason.QUALIFIED_OR_HANDED_OFF,)
    assert _reasons(db_session, handed_off) == (EligibilityReason.QUALIFIED_OR_HANDED_OFF,)
    assert _reasons(db_session, free) == ()


def test_open_duplicate_pair_blocks_both_people_decided_pair_does_not(
    db_session: Session,
) -> None:
    """An open pair blocks person A and person B; a decided pair blocks nobody (D-092)."""
    first, second = make_eligible_person(db_session), make_eligible_person(db_session)
    low, high = sorted((first, second), key=lambda person: person.id)
    make_duplicate_candidate(db_session, person_a_id=low.id, person_b_id=high.id)
    third, fourth = make_eligible_person(db_session), make_eligible_person(db_session)
    low2, high2 = sorted((third, fourth), key=lambda person: person.id)
    make_duplicate_candidate(
        db_session,
        person_a_id=low2.id,
        person_b_id=high2.id,
        status=DuplicateStatus.NOT_DUPLICATE,
        decided_at=NOW,
    )

    assert _reasons(db_session, first) == (EligibilityReason.POSSIBLE_DUPLICATE,)
    assert _reasons(db_session, second) == (EligibilityReason.POSSIBLE_DUPLICATE,)
    assert _reasons(db_session, third) == ()
    assert _reasons(db_session, fourth) == ()


def test_cooling_off_boundary(db_session: Session) -> None:
    """Contacted 89 days ago is cooling off; exactly 90 days ago is not (D-073, D-083)."""
    inside = make_eligible_person(db_session, last_contacted_at=NOW - timedelta(days=89))
    ended = make_eligible_person(db_session, last_contacted_at=NOW - timedelta(days=90))

    assert _reasons(db_session, inside) == (EligibilityReason.COOLING_OFF,)
    assert _reasons(db_session, ended) == ()


def test_cooling_off_length_follows_the_context(db_session: Session) -> None:
    """A shorter cooling_off_days in the context releases a lead contacted 30 days ago."""
    person = make_eligible_person(db_session, last_contacted_at=NOW - timedelta(days=30))
    short = EligibilityContext(now=NOW, cooling_off_days=14)

    assert check_eligibility(db_session, person, short).reasons == ()
    assert _reasons(db_session, person) == (EligibilityReason.COOLING_OFF,)


def test_contact_limit_counts_outbound_email_in_window(db_session: Session) -> None:
    """Two outbound touches are fine; the third inside 30 days blocks (decisions 1 and 6)."""
    person = make_eligible_person(db_session)
    for days_ago in (1, 10):
        make_touch(db_session, person=person, occurred_at=NOW - timedelta(days=days_ago))
    assert _reasons(db_session, person) == ()

    make_touch(
        db_session, person=person, occurred_at=NOW - timedelta(days=5), status=TouchStatus.BOUNCED
    )

    assert _reasons(db_session, person) == (EligibilityReason.CONTACT_LIMIT,)


def test_contact_limit_ignores_old_and_inbound_touches(db_session: Session) -> None:
    """Touches older than 30 days and inbound touches do not count toward the limit."""
    person = make_eligible_person(db_session)
    make_touch(db_session, person=person, occurred_at=NOW - timedelta(days=31))
    make_touch(db_session, person=person, occurred_at=NOW - timedelta(days=45))
    make_touch(
        db_session,
        person=person,
        direction=TouchDirection.INBOUND,
        status=TouchStatus.REPLIED,
        occurred_at=NOW - timedelta(days=2),
    )

    assert _reasons(db_session, person) == ()


def test_contact_limit_window_includes_its_first_day(db_session: Session) -> None:
    """A touch exactly 30 days old still counts toward the limit."""
    person = make_eligible_person(db_session)
    for days_ago in (30, 20, 3):
        make_touch(db_session, person=person, occurred_at=NOW - timedelta(days=days_ago))

    assert _reasons(db_session, person) == (EligibilityReason.CONTACT_LIMIT,)


def test_every_failing_reason_is_listed_in_order(db_session: Session) -> None:
    """A lead failing several rules gets all reasons in EligibilityReason order."""
    person = make_person(
        db_session, replied_at=NOW - timedelta(days=1), last_contacted_at=NOW - timedelta(days=1)
    )

    assert _reasons(db_session, person) == (
        EligibilityReason.NO_USABLE_EMAIL,
        EligibilityReason.REPLIED,
        EligibilityReason.COOLING_OFF,
    )


def test_unverified_email_warns_but_does_not_block(db_session: Session) -> None:
    """An unverified usable address gives a warning and the lead stays eligible (D-042)."""
    person = make_person(db_session)
    make_person_email(db_session, person=person)  # unverified work address by default

    result = check_eligibility(db_session, person, CTX)

    assert result.eligible
    assert result.warnings == (EligibilityWarning.UNVERIFIED_EMAIL,)


def test_eligible_queryset_returns_only_eligible_people(db_session: Session) -> None:
    """eligible_queryset keeps the clean lead and drops an opted-out one."""
    clean = make_eligible_person(db_session)
    opted_out = make_eligible_person(db_session)
    address = db_session.scalars(
        select(PersonEmail.normalized_address).where(PersonEmail.person_id == opted_out.id)
    ).one()
    make_opt_out(db_session, email_normalized=address)

    ids = {person.id for person in db_session.scalars(eligible_queryset(CTX))}

    assert clean.id in ids and opted_out.id not in ids
    assert eligible_person_ids(db_session, CTX) == ids


def test_build_context_uses_default_cooling_off_days(db_session: Session) -> None:
    """With no Settings row, build_context gives the 90-day default and the 3-per-30 limit."""
    ctx = build_context(db_session)

    assert ctx.cooling_off_days == 90
    assert (ctx.contact_limit, ctx.contact_window_days) == (3, 30)
