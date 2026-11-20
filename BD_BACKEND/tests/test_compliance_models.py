"""Tests for the compliance tables: opt-out rules, the single gate row, checklist and erasure.

Needed because the schema is the only thing enforcing the per-address opt-out (D-066), the
closed real-sending checklist (D-081) and the no-personal-data erasure record (D-099) until
the M3 and M8 services exist. Runs against real PostgreSQL through the shared db_session
fixture; all data is synthetic (M1 task A5).
"""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.compliance.models import (
    ChecklistItemKey,
    ComplianceChecklistItem,
    ComplianceGateStatus,
    ErasureRecord,
    OptOut,
    OptOutSource,
)
from app.core.clock import now
from app.core.models import User
from app.leads.models import Person

Rejected = Callable[[object, str], None]

ADDRESS = "jane@example.com"


# --- opt_outs ---


def test_opt_out_defaults(db_session: Session) -> None:
    """A new opt-out is active (not removed) and keeps its source and address."""
    row = OptOut(email_normalized=ADDRESS, source=OptOutSource.MANUAL)
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)

    assert row.source is OptOutSource.MANUAL
    assert row.removed_at is None
    assert row.reason is None


def test_second_active_opt_out_for_same_address_is_rejected(
    db_session: Session, assert_rejected: Rejected
) -> None:
    """Two active opt-outs for one address violate the partial unique index."""
    db_session.add(OptOut(email_normalized=ADDRESS, source=OptOutSource.MANUAL))
    db_session.flush()

    assert_rejected(
        OptOut(email_normalized=ADDRESS, source=OptOutSource.REPLY),
        "uq_opt_outs_active_email_normalized",
    )


def test_address_can_opt_out_again_after_removal(db_session: Session, user: User) -> None:
    """After a removal the same address can opt out again; both rows stay on record."""
    db_session.add(
        OptOut(
            email_normalized=ADDRESS,
            source=OptOutSource.MANUAL,
            removed_at=now(),
            removed_by=user.id,
            removal_reason="Added by mistake",
        )
    )
    db_session.add(OptOut(email_normalized=ADDRESS, source=OptOutSource.REPLY))
    db_session.flush()

    count = db_session.scalar(
        select(func.count()).select_from(OptOut).where(OptOut.email_normalized == ADDRESS)
    )
    assert count == 2


def test_different_addresses_do_not_conflict(db_session: Session) -> None:
    """Active opt-outs for two different addresses are both allowed."""
    db_session.add(OptOut(email_normalized="a@example.com", source=OptOutSource.IMPORTED))
    db_session.add(OptOut(email_normalized="b@example.com", source=OptOutSource.IMPORTED))
    db_session.flush()


def test_uppercase_address_is_rejected(db_session: Session, assert_rejected: Rejected) -> None:
    """An address with uppercase letters violates the lowercase CHECK."""
    assert_rejected(
        OptOut(email_normalized="Jane@Example.com", source=OptOutSource.MANUAL),
        "ck_opt_outs_email_normalized_lowercase",
    )


def test_unknown_source_is_rejected(db_session: Session) -> None:
    """A source outside manual/imported/reply violates the source CHECK."""
    # Raw SQL on purpose: the ORM enum would reject the value before the database sees it.
    with pytest.raises(IntegrityError, match="ck_opt_outs_source_valid"), db_session.begin_nested():
        db_session.execute(
            text(
                "INSERT INTO opt_outs (email_normalized, source, created_at) "
                "VALUES (:email, 'phone', now())"
            ),
            {"email": ADDRESS},
        )


def test_removal_without_reason_is_rejected(db_session: Session, assert_rejected: Rejected) -> None:
    """Setting removed_at without a removal_reason violates the reason CHECK (D-066)."""
    assert_rejected(
        OptOut(email_normalized=ADDRESS, source=OptOutSource.MANUAL, removed_at=now()),
        "ck_opt_outs_removal_has_reason",
    )


def test_removal_reason_on_active_opt_out_is_rejected(
    db_session: Session, assert_rejected: Rejected
) -> None:
    """A removal_reason on an opt-out that was not removed violates the together CHECK."""
    assert_rejected(
        OptOut(email_normalized=ADDRESS, source=OptOutSource.MANUAL, removal_reason="oops"),
        "ck_opt_outs_removal_fields_together",
    )


def test_deleting_user_keeps_opt_out(db_session: Session, user: User) -> None:
    """Deleting the user who recorded an opt-out keeps it and clears created_by (SET NULL)."""
    row = OptOut(email_normalized=ADDRESS, source=OptOutSource.MANUAL, created_by=user.id)
    db_session.add(row)
    db_session.flush()

    db_session.execute(delete(User).where(User.id == user.id))
    db_session.refresh(row)

    assert row.created_by is None


# --- compliance_gate_status ---


def test_gate_row_is_seeded_disabled(db_session: Session) -> None:
    """Migration 0008 leaves exactly one gate row with real sending disabled."""
    rows = db_session.scalars(select(ComplianceGateStatus)).all()

    assert len(rows) == 1
    assert rows[0].real_sending_enabled is False
    assert rows[0].enabled_at is None


def test_second_gate_row_is_rejected(db_session: Session, assert_rejected: Rejected) -> None:
    """A second gate row violates the singleton unique index."""
    assert_rejected(ComplianceGateStatus(), "uq_compliance_gate_status_singleton")


def test_gate_singleton_false_is_rejected(db_session: Session, assert_rejected: Rejected) -> None:
    """A gate row with singleton = false violates the singleton CHECK."""
    assert_rejected(
        ComplianceGateStatus(singleton=False), "ck_compliance_gate_status_singleton_true"
    )


def test_gate_enabled_without_timestamp_is_rejected(db_session: Session) -> None:
    """Enabling real sending without enabled_at violates the timestamp CHECK."""
    gate = db_session.scalars(select(ComplianceGateStatus)).one()
    gate.real_sending_enabled = True

    with pytest.raises(IntegrityError, match="ck_compliance_gate_status_enabled_has_timestamp"):
        db_session.flush()
    db_session.rollback()


# --- compliance_checklist_items ---


def test_checklist_is_seeded_with_the_four_d081_keys(db_session: Session) -> None:
    """Migration 0008 seeds exactly the four D-081 items, none passed."""
    rows = db_session.scalars(select(ComplianceChecklistItem)).all()

    assert {row.item_key for row in rows} == set(ChecklistItemKey)
    assert len(rows) == 4
    assert not any(row.is_passed for row in rows)


def test_duplicate_checklist_key_is_rejected(
    db_session: Session, assert_rejected: Rejected
) -> None:
    """A second row for an existing item key violates the unique index."""
    assert_rejected(
        ComplianceChecklistItem(item_key=ChecklistItemKey.FOOTER_SAVED),
        "uq_compliance_checklist_items_item_key",
    )


def test_passed_item_needs_timestamp(db_session: Session) -> None:
    """Marking an item passed without passed_at violates the timestamp CHECK."""
    item = db_session.scalars(select(ComplianceChecklistItem)).first()
    assert item is not None
    item.is_passed = True

    with pytest.raises(IntegrityError, match="ck_compliance_checklist_items_passed_has_timestamp"):
        db_session.flush()
    db_session.rollback()


# --- erasure_records ---


def test_erasure_record_survives_without_a_person(db_session: Session, user: User) -> None:
    """An erasure record stores a person id with no FK, so it needs no existing person."""
    record = ErasureRecord(
        former_person_id=uuid.uuid4(),
        erased_by=user.id,
        reason="Prospect asked to be forgotten",
        removed_counts={"raw_rows": 2, "emails": 1},
    )
    db_session.add(record)
    db_session.flush()
    db_session.refresh(record)

    assert record.removed_counts == {"raw_rows": 2, "emails": 1}
    assert record.erased_at is not None


def test_erasure_record_counts_default_to_empty(db_session: Session) -> None:
    """removed_counts defaults to an empty object when not given."""
    record = ErasureRecord(former_person_id=uuid.uuid4(), reason="Test")
    db_session.add(record)
    db_session.flush()
    db_session.refresh(record)

    assert record.removed_counts == {}


def test_erasure_record_stays_when_person_is_deleted(db_session: Session, person: Person) -> None:
    """Deleting the person leaves the erasure record untouched (no FK to people)."""
    record = ErasureRecord(former_person_id=person.id, reason="Test")
    db_session.add(record)
    db_session.flush()

    db_session.execute(delete(Person).where(Person.id == person.id))

    assert db_session.get(ErasureRecord, record.id) is not None
