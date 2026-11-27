"""Assigning the leads of an import whose source owner could not be matched (M2-A4, D-075).

Needed because the pipeline only sets an owner when the source owner text matches exactly one
user (imports.owners); the rest stay "Unassigned" and a manager must pick an owner. The
unmatched leads are derived on read, with no extra table: a lead of the import (raw_rows.person_id)
with no owner, grouped by the owner text that the saved "owner_name" column holds in its raw
row. A manager then assigns a whole group to one user. The routes in imports.assignment_api
call these functions. Assignment only fills empty owners, so it never takes a lead away from
its owner (D-001, D-075).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import (
    ColumnElement,
    Select,
    String,
    distinct,
    func,
    literal,
    select,
    type_coerce,
    update,
)
from sqlalchemy.orm import Session

from app.audit.services import AuditAction, record
from app.core.models import User
from app.imports.errors import AssignErrorKind, AssignRejectedError
from app.imports.models import ColumnMapping, ImportFile, ImportStatus, RawRow
from app.imports.raw_keys import original_value_keys
from app.imports.upload import get_import_for_viewer
from app.leads.models import Person

OWNER_NAME_FIELD = "owner_name"
# Leads can be listed while the job runs (a partial view), but assigned only once it is done,
# so an assignment never races the job that is still writing owners.
LISTABLE_STATUSES = frozenset({ImportStatus.PROCESSING, ImportStatus.COMPLETED})

NOT_ASSIGNABLE_YET_MESSAGE = "Owners can be assigned after the import has completed."
USER_NOT_ASSIGNABLE_MESSAGE = "Choose an active user to assign the leads to."


@dataclass(frozen=True, slots=True)
class UnmatchedOwner:
    """One owner text that matched no user, with the unowned leads that carry it.

    Attributes:
        owner_group: The normalised text (trimmed, lower case); send it back to assign the group.
            Empty for the "no owner given" group.
        display_name: The text as first written in the file (empty for the blank group).
        lead_count: Distinct leads of this import that still have no owner.
    """

    owner_group: str
    display_name: str
    lead_count: int


@dataclass(frozen=True, slots=True)
class AssignmentResult:
    """What an assignment did: leads that got the owner, and leads already owned (left alone)."""

    assigned: int
    skipped: int


@dataclass(frozen=True, slots=True)
class AssignableUser:
    """An active user a manager can assign leads to."""

    id: uuid.UUID
    email: str


def _trimmed(text: ColumnElement[str]) -> ColumnElement[str]:
    """SQL: the text without leading and trailing whitespace of any kind."""
    return func.regexp_replace(text, r"^\s+|\s+$", "", "g")


def _normalised(text: ColumnElement[str]) -> ColumnElement[str]:
    """SQL: the grouping form of an owner text, trimmed and lower case (the listing's key)."""
    return func.lower(_trimmed(text))


def _owner_key(db: Session, import_id: uuid.UUID) -> str | None:
    """The raw_rows.original_values key of the owner_name column, or None if it is unmapped.

    The key is derived from the saved headers with the pipeline's own rule (imports.raw_keys),
    so it matches how the raw rows were written.
    """
    columns = db.scalars(
        select(ColumnMapping)
        .where(ColumnMapping.import_file_id == import_id)
        .order_by(ColumnMapping.column_index)
    ).all()
    owner_columns = [c for c in columns if c.target_field == OWNER_NAME_FIELD]
    if not owner_columns:
        return None
    keys = original_value_keys([c.source_header or "" for c in columns], len(columns))
    return keys[columns.index(owner_columns[0])]


def _owner_text(owner_key: str | None) -> ColumnElement[str]:
    """SQL: the raw owner text of a row; empty when the column is unmapped or the cell is empty."""
    if owner_key is None:
        return literal("", String)
    cell = type_coerce(RawRow.original_values.op("->>")(owner_key), String)
    return func.coalesce(cell, "")


def _import_leads(import_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """Distinct leads (people) that rows of this import created or updated."""
    return select(RawRow.person_id).where(
        RawRow.import_file_id == import_id, RawRow.person_id.is_not(None)
    )


def list_unmatched_owners(db: Session, actor: User, import_id: uuid.UUID) -> list[UnmatchedOwner]:
    """List the owner texts of an import that left leads without an owner, biggest group first.

    Empty before the import starts processing. Reps cannot reach this (the route needs
    ASSIGN_LEADS); managers and admins see every import (imports.access).

    Raises:
        ImportNotFoundError: If the import does not exist or the actor may not see it.
    """
    import_file = get_import_for_viewer(db, actor, import_id)
    if import_file.status not in LISTABLE_STATUSES:
        return []
    text = _owner_text(_owner_key(db, import_id))
    group = _normalised(text)
    rows = db.execute(
        select(group, func.min(_trimmed(text)), func.count(distinct(Person.id)))
        .select_from(RawRow)
        .join(Person, Person.id == RawRow.person_id)
        .where(RawRow.import_file_id == import_id, Person.owner_id.is_(None))
        .group_by(group)
        .order_by(func.count(distinct(Person.id)).desc(), group)
    ).all()
    return [UnmatchedOwner(owner_group=g, display_name=d, lead_count=c) for g, d, c in rows]


def list_assignable_users(db: Session) -> list[AssignableUser]:
    """Every active user, ordered by email, for the "assign to" picker."""
    rows = db.execute(
        select(User.id, User.email).where(User.is_active.is_(True)).order_by(User.email)
    ).all()
    return [AssignableUser(id=user_id, email=email) for user_id, email in rows]


def assign_owner_group(
    db: Session,
    actor: User,
    import_id: uuid.UUID,
    owner_group: str,
    user_id: uuid.UUID,
    *,
    ip_address: str | None = None,
) -> AssignmentResult:
    """Give every still-unowned lead of one owner text in an import to one user (D-075).

    The group is matched on the same normalised text the listing returns. Only leads with no
    owner change (the UPDATE repeats the check), so a double click, a race or a lead that got an
    owner meanwhile is never overwritten; those leads are counted as skipped. One audit event
    records the counts and the target user, not the owner text (a permanent log holds no lead
    data). Commits.

    Raises:
        ImportNotFoundError: If the import does not exist or the actor may not see it.
        AssignRejectedError: NOT_ASSIGNABLE_YET if the import has not completed;
            USER_NOT_ASSIGNABLE if the user does not exist or is inactive.
    """
    import_file = get_import_for_viewer(db, actor, import_id)
    _require_completed(import_file)
    target = db.get(User, user_id)
    if target is None or not target.is_active:
        raise AssignRejectedError(AssignErrorKind.USER_NOT_ASSIGNABLE, USER_NOT_ASSIGNABLE_MESSAGE)

    group = _normalised(_owner_text(_owner_key(db, import_id)))
    wanted = _normalised(literal(owner_group, String))
    group_leads = select(RawRow.person_id).where(
        RawRow.import_file_id == import_id,
        RawRow.person_id.is_not(None),
        group == wanted,
    )
    in_group = db.scalar(select(func.count(distinct(Person.id))).where(Person.id.in_(group_leads)))
    updated = db.execute(
        update(Person)
        .where(Person.id.in_(group_leads), Person.owner_id.is_(None))
        .values(owner_id=user_id)
        .returning(Person.id)
    ).all()
    result = AssignmentResult(assigned=len(updated), skipped=max((in_group or 0) - len(updated), 0))
    record(
        db,
        action=AuditAction.IMPORT_OWNER_ASSIGNED,
        actor_user_id=actor.id,
        object_type="import_file",
        object_id=str(import_id),
        summary={
            "assigned_user_id": str(user_id),
            "assigned": result.assigned,
            "skipped": result.skipped,
            "blank_group": not owner_group.strip(),
        },
        ip_address=ip_address,
    )
    db.commit()
    return result


def _require_completed(import_file: ImportFile) -> None:
    """Refuse assignment while the job may still write owners.

    Raises:
        AssignRejectedError: NOT_ASSIGNABLE_YET unless the import is COMPLETED.
    """
    if import_file.status is not ImportStatus.COMPLETED:
        raise AssignRejectedError(AssignErrorKind.NOT_ASSIGNABLE_YET, NOT_ASSIGNABLE_YET_MESSAGE)
