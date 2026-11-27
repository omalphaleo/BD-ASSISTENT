"""Parity test: the SQL and record versions of every eligibility rule agree (M3-A1).

Needed because search uses the bulk SQL expressions while sending will use the per-person
check, and the two could drift (plan section 14 G, skill outreach-compliance). It builds many
synthetic people with random combinations of facts, around every time boundary, and requires
the same answer from both versions for each reason, and for the unverified-email warning
that search shows as a badge (added in M3-A2).
"""

import random
from datetime import UTC, datetime, timedelta

from factories.compliance import make_opt_out
from factories.leads import (
    make_duplicate_candidate,
    make_lead_status_flag,
    make_person,
    make_person_email,
    make_touch,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.contracts import EligibilityContext, EligibilityReason, EligibilityWarning
from app.compliance.eligibility import (
    check_eligibility,
    eligible_person_ids,
    ineligible_expression,
    reason_expression,
    warning_expression,
)
from app.leads.models import (
    EmailType,
    EmailVerificationStatus,
    LeadStatusFlagType,
    Person,
    TouchDirection,
    TouchStatus,
)

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
CTX = EligibilityContext(now=NOW, cooling_off_days=90)
PEOPLE_COUNT = 120
RANDOM_SEED = 20261127  # fixed so a failure can be reproduced


def _maybe_days_ago(rng: random.Random) -> datetime | None:
    """Return a time near a boundary (89, 90, 91 days; 29, 30, 31 days) or None."""
    if rng.random() < 0.4:
        return None
    return NOW - timedelta(days=rng.choice([1, 29, 30, 31, 89, 90, 91, 200]))


def _build_people(db: Session, rng: random.Random) -> list[Person]:
    """Insert PEOPLE_COUNT leads whose facts are random, so every rule is hit both ways."""
    people: list[Person] = []
    for _ in range(PEOPLE_COUNT):
        person = make_person(
            db,
            replied_at=NOW if rng.random() < 0.15 else None,
            last_contacted_at=_maybe_days_ago(rng),
        )
        for _ in range(rng.choice([0, 1, 1, 2])):
            email = make_person_email(
                db,
                person=person,
                type=rng.choice([EmailType.WORK, EmailType.WORK, EmailType.PERSONAL]),
                is_invalid=rng.random() < 0.15,
            )
            if rng.random() < 0.15:
                make_opt_out(db, email_normalized=email.normalized_address)
            if rng.random() < 0.05:
                # A removed opt-out must not count.
                make_opt_out(
                    db,
                    email_normalized=f"old.{email.normalized_address}",
                    removed_at=NOW,
                    removal_reason="test",
                )
        if rng.random() < 0.15:
            make_lead_status_flag(
                db,
                person=person,
                flag_type=rng.choice(list(LeadStatusFlagType)),
            )
        for _ in range(rng.choice([0, 0, 1, 2, 3, 4])):
            make_touch(
                db,
                person=person,
                occurred_at=NOW - timedelta(days=rng.choice([0, 15, 29, 30, 31, 60])),
                direction=rng.choice([TouchDirection.OUTBOUND] * 3 + [TouchDirection.INBOUND]),
                status=rng.choice(list(TouchStatus)),
            )
        people.append(person)
    # Pair up some people as open duplicates (A < B is a table constraint).
    for first, second in zip(people[0:30:2], people[1:30:2], strict=True):
        low, high = sorted((first, second), key=lambda p: p.id)
        make_duplicate_candidate(db, person_a_id=low.id, person_b_id=high.id)
    return people


def test_sql_and_record_versions_agree_for_every_reason(db_session: Session) -> None:
    """For every reason, the SQL set equals the set of people whose record check lists it."""
    people = _build_people(db_session, random.Random(RANDOM_SEED))
    results = {person.id: check_eligibility(db_session, person, CTX) for person in people}

    for reason in EligibilityReason:
        sql_ids = set(
            db_session.scalars(
                select(Person.id).where(Person.id.in_(results), reason_expression(reason, CTX))
            )
        )
        record_ids = {pid for pid, result in results.items() if reason in result.reasons}
        assert sql_ids == record_ids, reason
        # The generated data must actually exercise the rule, or the test proves nothing.
        assert record_ids and len(record_ids) < len(people), reason


def test_unverified_email_warning_sql_matches_record_check(db_session: Session) -> None:
    """The unverified-email warning (a badge, not a blocker, D-042): SQL set equals the record set.

    Own generator so the other tests' random streams stay unchanged: each person gets 0-3
    addresses with random type, validity and verification.
    """
    rng = random.Random(RANDOM_SEED + 2)
    people = []
    for _ in range(PEOPLE_COUNT):
        person = make_person(db_session)
        for _ in range(rng.choice([0, 1, 2, 3])):
            make_person_email(
                db_session,
                person=person,
                type=rng.choice([EmailType.WORK, EmailType.WORK, EmailType.PERSONAL]),
                is_invalid=rng.random() < 0.2,
                verification_status=rng.choice(list(EmailVerificationStatus)),
            )
        people.append(person)
    record_ids = {
        person.id
        for person in people
        if EligibilityWarning.UNVERIFIED_EMAIL
        in check_eligibility(db_session, person, CTX).warnings
    }
    sql_ids = set(
        db_session.scalars(
            select(Person.id).where(
                Person.id.in_([p.id for p in people]),
                warning_expression(EligibilityWarning.UNVERIFIED_EMAIL, CTX),
            )
        )
    )

    assert sql_ids == record_ids
    # The data must exercise the warning both ways, or the test proves nothing.
    assert record_ids and len(record_ids) < len(people)


def test_bulk_eligible_set_matches_record_verdicts(db_session: Session) -> None:
    """eligible_queryset and ineligible_expression equal the per-person eligible verdicts."""
    people = _build_people(db_session, random.Random(RANDOM_SEED + 1))
    expected = {p.id for p in people if check_eligibility(db_session, p, CTX).eligible}

    assert eligible_person_ids(db_session, CTX) >= expected  # other tests' rows may add more
    ineligible = set(db_session.scalars(select(Person.id).where(ineligible_expression(CTX))))
    assert not (ineligible & expected)
    assert {p.id for p in people} - ineligible == expected
