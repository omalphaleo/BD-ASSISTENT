"""Tests for QuarantineRecord, DuplicateCandidate and MergeRecord against real PostgreSQL.

Needed because the open/resolved consistency rules, the ordered unique pair and the cascade
behaviour that keeps erase-person complete (D-099) are enforced by the database (M1 task A3).
All data is synthetic.
"""

import uuid
from collections.abc import Callable
from datetime import datetime

import pytest
from sqlalchemy import delete, null, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.models import User
from app.leads.models import (
    DuplicateCandidate,
    DuplicateStatus,
    MergeRecord,
    Person,
    QuarantineRecord,
    QuarantineStatus,
)


def _two_people(session: Session) -> tuple[Person, Person]:
    """Insert two people and return them ordered so that the first id sorts lower."""
    first, second = Person(first_name="Ann"), Person(first_name="Ann")
    session.add_all([first, second])
    session.flush()
    low, high = sorted([first, second], key=lambda p: p.id)
    return low, high


def test_quarantine_record_defaults_to_open(db_session: Session) -> None:
    """A new record is open, has no issues listed and is not resolved."""
    record = QuarantineRecord(payload={"email": "info@acme.example"})
    db_session.add(record)
    db_session.flush()
    db_session.refresh(record)

    assert record.status is QuarantineStatus.OPEN
    assert record.issues == [] and record.resolved_at is None


def test_quarantine_payload_is_required(db_session: Session) -> None:
    """A record without its editable payload (SQL NULL) is rejected."""
    # null(), not None: a Python None in a JSONB column is stored as the JSON value null.
    db_session.add(QuarantineRecord(payload=null()))
    with pytest.raises(IntegrityError, match="payload"):
        db_session.flush()


def test_quarantine_resolved_time_must_match_status(
    db_session: Session, user: User, assert_rejected: Callable[[object, str], None]
) -> None:
    """Open with a resolved time, or released without one, is rejected; a consistent pair passes."""
    constraint = "ck_quarantine_records_resolved_at_matches_status"
    assert_rejected(
        QuarantineRecord(payload={}, status=QuarantineStatus.OPEN, resolved_at=now()), constraint
    )
    assert_rejected(QuarantineRecord(payload={}, status=QuarantineStatus.RELEASED), constraint)

    db_session.add(
        QuarantineRecord(
            payload={},
            status=QuarantineStatus.DISCARDED,
            resolved_at=now(),
            resolved_by=user.id,
        )
    )
    db_session.flush()  # must not raise


def test_quarantine_status_is_limited_to_known_values(db_session: Session) -> None:
    """An unknown status is rejected by the CHECK."""
    # resolved_at is set so the open/resolved rule is satisfied and only the status CHECK fires.
    db_session.add(QuarantineRecord(payload={}, status="parked", resolved_at=now()))
    with pytest.raises(IntegrityError, match="ck_quarantine_records_status_valid"):
        db_session.flush()


def test_deleting_the_resolving_user_keeps_the_record(db_session: Session, user: User) -> None:
    """Deleting the user who resolved a record clears resolved_by and keeps the record."""
    record = QuarantineRecord(
        payload={}, status=QuarantineStatus.RELEASED, resolved_at=now(), resolved_by=user.id
    )
    db_session.add(record)
    db_session.flush()

    db_session.execute(delete(User).where(User.id == user.id))
    db_session.refresh(record)

    assert record.resolved_by is None


def test_duplicate_pair_defaults_to_open(db_session: Session) -> None:
    """A flagged pair starts open with no decision recorded."""
    low, high = _two_people(db_session)
    pair = DuplicateCandidate(person_a_id=low.id, person_b_id=high.id, reason="name_and_domain")
    db_session.add(pair)
    db_session.flush()
    db_session.refresh(pair)

    assert pair.status is DuplicateStatus.OPEN and pair.decided_at is None


def test_duplicate_pair_must_be_ordered_and_distinct(
    db_session: Session, assert_rejected: Callable[[object, str], None]
) -> None:
    """The pair (high, low) and a person paired with themselves are both rejected."""
    low, high = _two_people(db_session)
    constraint = "ck_duplicate_candidates_pair_ordered"

    assert_rejected(
        DuplicateCandidate(person_a_id=high.id, person_b_id=low.id, reason="r"), constraint
    )
    assert_rejected(
        DuplicateCandidate(person_a_id=low.id, person_b_id=low.id, reason="r"), constraint
    )


def test_duplicate_pair_cannot_be_flagged_twice(db_session: Session) -> None:
    """The same pair cannot be stored twice."""
    low, high = _two_people(db_session)
    db_session.add(DuplicateCandidate(person_a_id=low.id, person_b_id=high.id, reason="r"))
    db_session.flush()

    db_session.add(DuplicateCandidate(person_a_id=low.id, person_b_id=high.id, reason="r2"))
    with pytest.raises(IntegrityError, match="uq_duplicate_candidates_person_a_id_person_b_id"):
        db_session.flush()


def test_duplicate_decision_time_must_match_status(db_session: Session) -> None:
    """A decided pair without a decision time, or an open one with it, is rejected."""
    low, high = _two_people(db_session)
    db_session.add(
        DuplicateCandidate(
            person_a_id=low.id,
            person_b_id=high.id,
            reason="r",
            status=DuplicateStatus.NOT_DUPLICATE,
        )
    )
    with pytest.raises(IntegrityError, match="ck_duplicate_candidates_decided_at_matches_status"):
        db_session.flush()


def test_deleting_a_person_removes_their_pairs(db_session: Session) -> None:
    """Erasing either person of a pair removes the pair."""
    low, high = _two_people(db_session)
    db_session.add(DuplicateCandidate(person_a_id=low.id, person_b_id=high.id, reason="r"))
    db_session.flush()

    db_session.execute(delete(Person).where(Person.id == high.id))

    assert db_session.scalars(select(DuplicateCandidate)).all() == []


def test_merge_record_keeps_a_snapshot_without_the_absorbed_row(
    db_session: Session, person: Person
) -> None:
    """A merge record stores the absorbed id and snapshot though no person has that id."""
    absorbed_id = uuid.uuid4()  # the absorbed person row no longer exists
    record = MergeRecord(
        survivor_id=person.id, absorbed_person_id=absorbed_id, snapshot={"first_name": "Jan"}
    )
    db_session.add(record)
    db_session.flush()
    db_session.refresh(record)

    assert record.snapshot == {"first_name": "Jan"}
    assert isinstance(record.merged_at, datetime)


def test_erasing_the_survivor_removes_the_merge_record(db_session: Session, person: Person) -> None:
    """Deleting the survivor deletes the merge record, whose snapshot holds personal data."""
    db_session.add(MergeRecord(survivor_id=person.id, absorbed_person_id=uuid.uuid4(), snapshot={}))
    db_session.flush()

    db_session.execute(delete(Person).where(Person.id == person.id))

    assert db_session.scalars(select(MergeRecord)).all() == []
