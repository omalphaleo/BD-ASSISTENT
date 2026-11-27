"""Merges incoming import values into a stored person or company (M2-B4, D-046, D-050, D-008).

Needed so a re-import brings leads up to date without damaging them: the latest import wins
per field, a blank incoming value never erases stored data, and every address ever seen is
kept. Each value that really changes is returned as a FieldChange and stored in one
ImportChange row per person and import (the one-time "what changed" summary of D-050; not a
permanent history, D-008). Nothing here commits; the caller owns the transaction.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.imports.models import ImportChange, ImportReport
from app.leads.contracts import FieldChange, JsonScalar
from app.leads.models import (
    EmailType,
    EmailVerificationStatus,
    Person,
    PersonEmail,
)

EMAILS_FIELD = "emails"


@dataclass(frozen=True, slots=True)
class IncomingEmail:
    """One address of an incoming row, already normalized and classified.

    Attributes:
        address: The address as received, trimmed.
        normalized_address: Lowercase form used for matching.
        type: Work, personal or generic (D-072).
        verified: True when the source says the address is verified.
        is_main: True for the address ingest_row chose as the person's main one.
    """

    address: str
    normalized_address: str
    type: EmailType
    verified: bool = False
    is_main: bool = False


def _as_json(value: object) -> JsonScalar:
    """Convert a stored value to something JSON can hold (Decimals and times become text)."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return ", ".join(str(item) for item in value)
    return str(value)


def _is_blank(value: object) -> bool:
    """A missing value, blank text or an empty list: something that must never erase data."""
    return value is None or (isinstance(value, str) and not value.strip()) or value == []


def merge_attributes(
    target: object, incoming: Mapping[str, object], *, prefix: str = ""
) -> list[FieldChange]:
    """Copy incoming values onto a person or company; latest wins, blank never erases.

    Args:
        target: The stored Person or Company; its attributes are set in place.
        incoming: Column name to new value. Names the target does not have are ignored.
        prefix: Put before each reported field name (e.g. "company.") so changes to a
            person's company are told apart from changes to the person.

    Returns:
        One FieldChange per value that actually differs; an equal value reports nothing.
    """
    changes: list[FieldChange] = []
    for name, new_value in incoming.items():
        if _is_blank(new_value) or not hasattr(target, name):
            continue
        old_value = getattr(target, name)
        if old_value == new_value:
            continue
        setattr(target, name, new_value)
        changes.append(FieldChange(f"{prefix}{name}", _as_json(old_value), _as_json(new_value)))
    return changes


def merge_emails(
    db: Session, person: Person, incoming: Sequence[IncomingEmail]
) -> list[FieldChange]:
    """Add the addresses the person does not have yet; never remove or rewrite one (D-072).

    All addresses are kept, but only the main work address is primary, and only when the
    person has no primary yet: an existing primary is never replaced. Secondary and tertiary
    addresses are stored here and never used for outreach (D-072).

    Returns:
        One change per new address, as {"field": "emails", "old": None, "new": address}.
    """
    stored = list(
        db.execute(select(PersonEmail).where(PersonEmail.person_id == person.id)).scalars()
    )
    known = {email.normalized_address for email in stored}
    has_primary = any(email.is_primary for email in stored)
    changes: list[FieldChange] = []
    for email in incoming:
        if email.normalized_address in known:
            continue
        known.add(email.normalized_address)
        makes_primary = email.is_main and not has_primary
        has_primary = has_primary or makes_primary
        db.add(
            PersonEmail(
                person_id=person.id,
                address=email.address,
                normalized_address=email.normalized_address,
                type=email.type,
                verification_status=(
                    EmailVerificationStatus.VERIFIED
                    if email.verified
                    else EmailVerificationStatus.UNVERIFIED
                ),
                is_primary=makes_primary,
            )
        )
        changes.append(FieldChange(EMAILS_FIELD, None, email.address))
    db.flush()
    return changes


def _changes_as_json(changes: Sequence[FieldChange]) -> list[dict[str, JsonScalar]]:
    """Serialize changes as the {"field", "old", "new"} objects ImportChange.changes holds."""
    return [{"field": c.field, "old": c.old, "new": c.new} for c in changes]


def record_import_change(
    db: Session, import_file_id: uuid.UUID, person_id: uuid.UUID, changes: Sequence[FieldChange]
) -> bool:
    """Write what an import changed on one person into its ImportChange row (D-050).

    There is one row per person and import (unique constraint), so a person updated by two
    rows of the same file keeps one row: the first old value and the latest new value per
    field. Nothing is written when there are no changes or the file has no ImportReport yet
    (the report is created by the import pipeline).

    Returns:
        True when a row was written or extended.
    """
    if not changes:
        return False
    report_id = db.execute(
        select(ImportReport.id).where(ImportReport.import_file_id == import_file_id)
    ).scalar_one_or_none()
    if report_id is None:
        return False
    row = db.execute(
        select(ImportChange).where(
            ImportChange.import_report_id == report_id, ImportChange.person_id == person_id
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(
            ImportChange(
                import_report_id=report_id, person_id=person_id, changes=_changes_as_json(changes)
            )
        )
    else:
        stored_items: list[dict[str, JsonScalar]] = list(row.changes)  # type: ignore[call-overload]
        by_field = {str(item["field"]): item for item in stored_items}
        for change in _changes_as_json(changes):
            field = str(change["field"])
            if field != EMAILS_FIELD and field in by_field:
                # Same field changed twice in one import: first old value, latest new value.
                by_field[field]["new"] = change["new"]
            else:
                stored_items.append(change)
                by_field.setdefault(field, change)
        # Assign a new list: JSONB columns are not tracked for in-place changes.
        row.changes = stored_items
    db.flush()
    return True
