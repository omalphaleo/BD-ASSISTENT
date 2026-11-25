"""Test factories for the compliance tables: opt-outs, gate status, checklist, erasure records.

Needed so tests build valid synthetic compliance rows in one line. Migration 0008 already
inserts the single gate-status row and the checklist items, so their factories return the
existing row (applying overrides) instead of inserting a second one. All data is synthetic.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.models import (
    ChecklistItemKey,
    ComplianceChecklistItem,
    ComplianceGateStatus,
    ErasureRecord,
    OptOut,
    OptOutSource,
)
from factories.common import next_number, persist


def make_opt_out(session: Session, **overrides: object) -> OptOut:
    """Insert an active manual opt-out for a unique lower-case address."""
    fields: dict[str, object] = {
        "email_normalized": f"optout{next_number()}@example.com",
        "source": OptOutSource.MANUAL,
    }
    return persist(session, OptOut(**{**fields, **overrides}))


def make_compliance_gate_status(session: Session, **overrides: object) -> ComplianceGateStatus:
    """Return the seeded gate-status row (real sending disabled), with overrides applied."""
    gate = session.scalars(select(ComplianceGateStatus)).one()
    for name, value in overrides.items():
        setattr(gate, name, value)
    session.flush()
    return gate


def make_compliance_checklist_item(
    session: Session,
    item_key: ChecklistItemKey = ChecklistItemKey.UNSUBSCRIBE_TESTED,
    **overrides: object,
) -> ComplianceChecklistItem:
    """Return the seeded checklist item for item_key (not passed), with overrides applied."""
    item = session.scalars(
        select(ComplianceChecklistItem).where(ComplianceChecklistItem.item_key == item_key)
    ).one()
    for name, value in overrides.items():
        setattr(item, name, value)
    session.flush()
    return item


def make_erasure_record(session: Session, **overrides: object) -> ErasureRecord:
    """Insert an erasure record for a person id that no longer exists (erased people are gone)."""
    fields: dict[str, object] = {"former_person_id": uuid.uuid4(), "reason": "Synthetic request."}
    return persist(session, ErasureRecord(**{**fields, **overrides}))
