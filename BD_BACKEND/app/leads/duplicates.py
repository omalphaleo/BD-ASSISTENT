"""Service for reviewing possible duplicates: merge or "not a duplicate" (M2-B5, D-092, D-108).

Needed because ingest_row never merges an uncertain match by itself: it imports the row as a
separate person and opens a DuplicateCandidate pair (leads/ingest.py). A manager or admin
settles each pair here. Merging keeps one person (the survivor), lets the reviewer pick every
field with the most recent value pre-selected, keeps every email address, and moves the
absorbed person's history (touches, timeline events, notes, flags, campaign and mail rows, raw
rows) onto the survivor, so no history is lost; a MergeRecord keeps a snapshot of the absorbed
person (D-108). "Not a duplicate" is remembered so the pair is never raised again (matching.py).
Each action is audited and committed here; routes are thin and enforce REVIEW_DUPLICATES.
Audit summaries hold ids and field names only, never lead values.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import Table, delete, exists, func, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.schema import Column, UniqueConstraint

from app.audit.services import AuditAction, record
from app.core.clock import now
from app.core.models import User
from app.db import Base
from app.leads.matching import find_duplicate_decision
from app.leads.models import (
    Company,
    DuplicateCandidate,
    DuplicateStatus,
    LeadEvent,
    MergeRecord,
    Person,
    PersonEmail,
)

AUDIT_OBJECT_TYPE = "duplicate_candidate"
PERSON_MERGED_EVENT = "person.merged"
# Fields the reviewer picks one by one. Names are the Person column names.
MERGE_FIELDS = (
    "first_name",
    "last_name",
    "title",
    "seniority",
    "department",
    "city",
    "state",
    "country",
    "timezone",
    "source_status",
    "source_stage",
    "linkedin_url",
    "source_record_id",
)
# Handled by the pair logic itself, so the generic child move leaves it alone.
_SKIPPED_TABLES = frozenset({DuplicateCandidate.__tablename__})
Side = Literal["a", "b"]


class DuplicateNotFoundError(Exception):
    """The candidate id does not exist."""


class DuplicateNotOpenError(Exception):
    """The pair was already merged or marked "not a duplicate"."""


class DuplicateFieldError(Exception):
    """A merge value names a field that cannot be merged, or is too long."""


class DuplicateSurvivorError(Exception):
    """The chosen survivor is not one of the two people of the pair."""


@dataclass(frozen=True, slots=True)
class PersonCard:
    """One side of a pair as the review screen shows it."""

    person: Person
    emails: list[str]
    company_name: str | None


@dataclass(frozen=True, slots=True)
class CandidateView:
    """A duplicate pair with both people and, per field, which side is pre-selected."""

    candidate: DuplicateCandidate
    person_a: PersonCard
    person_b: PersonCard
    suggested: dict[str, Side]


def _blank(value: object) -> bool:
    """A missing value or blank text."""
    return value is None or (isinstance(value, str) and not value.strip())


def _newer_side(person_a: Person, person_b: Person) -> Side:
    """The side whose record was updated last; "a" on a tie (D-108: the latest value wins)."""
    return "b" if person_b.updated_at > person_a.updated_at else "a"


def suggest_side(person_a: Person, person_b: Person, field: str) -> Side:
    """Pre-select the more recent record's value, or the other's when that one is blank."""
    first = _newer_side(person_a, person_b)
    people = {"a": person_a, "b": person_b}
    other: Side = "b" if first == "a" else "a"
    return first if not _blank(getattr(people[first], field)) else other


def _card(db: Session, person: Person) -> PersonCard:
    """Collect what the screen shows for one person: all addresses and the company name."""
    emails = db.scalars(
        select(PersonEmail.address)
        .where(PersonEmail.person_id == person.id)
        .order_by(PersonEmail.is_primary.desc(), PersonEmail.created_at, PersonEmail.id)
    ).all()
    company = db.get(Company, person.company_id) if person.company_id else None
    return PersonCard(
        person=person, emails=list(emails), company_name=company.name if company else None
    )


def _view(db: Session, candidate: DuplicateCandidate) -> CandidateView:
    """Build the view of one pair."""
    person_a = db.get(Person, candidate.person_a_id)
    person_b = db.get(Person, candidate.person_b_id)
    assert person_a is not None and person_b is not None  # both ids are foreign keys
    return CandidateView(
        candidate=candidate,
        person_a=_card(db, person_a),
        person_b=_card(db, person_b),
        suggested={field: suggest_side(person_a, person_b, field) for field in MERGE_FIELDS},
    )


def list_candidates(
    db: Session, *, status: DuplicateStatus, limit: int, offset: int
) -> tuple[list[CandidateView], int]:
    """List pairs with the given status, oldest first so the longest-waiting come first."""
    base = select(DuplicateCandidate).where(DuplicateCandidate.status == status)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(DuplicateCandidate.created_at, DuplicateCandidate.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [_view(db, row) for row in rows], total


def get_candidate(db: Session, candidate_id: uuid.UUID) -> CandidateView:
    """Return one pair.

    Raises:
        DuplicateNotFoundError: If the id does not exist.
    """
    candidate = db.get(DuplicateCandidate, candidate_id)
    if candidate is None:
        raise DuplicateNotFoundError
    return _view(db, candidate)


def _lock_open(db: Session, candidate_id: uuid.UUID) -> DuplicateCandidate:
    """Load a pair for update and require it to be open (two reviewers cannot both act)."""
    candidate = db.get(DuplicateCandidate, candidate_id, with_for_update=True)
    if candidate is None:
        raise DuplicateNotFoundError
    if candidate.status != DuplicateStatus.OPEN:
        raise DuplicateNotOpenError
    return candidate


def mark_not_duplicate(
    db: Session, actor: User, candidate_id: uuid.UUID, *, ip_address: str | None = None
) -> CandidateView:
    """Record that the two people are different; the decision is remembered (D-092).

    Raises:
        DuplicateNotFoundError: If the id does not exist.
        DuplicateNotOpenError: If the pair was already decided.
    """
    candidate = _lock_open(db, candidate_id)
    candidate.status = DuplicateStatus.NOT_DUPLICATE
    candidate.decided_by = actor.id
    candidate.decided_at = now()
    record(
        db,
        action=AuditAction.DUPLICATE_MARKED_DISTINCT,
        actor_user_id=actor.id,
        object_type=AUDIT_OBJECT_TYPE,
        object_id=str(candidate.id),
        summary={
            "person_a_id": str(candidate.person_a_id),
            "person_b_id": str(candidate.person_b_id),
        },
        ip_address=ip_address,
    )
    db.commit()
    return _view(db, candidate)


# --- merge ---------------------------------------------------------------------------------


def _as_json(value: object) -> object:
    """Convert a column value to something JSON can store."""
    if value is None or isinstance(value, bool | int | float | str | list | dict):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _snapshot(db: Session, person: Person) -> dict[str, object]:
    """Everything needed to see the absorbed person later: its columns and its addresses."""
    data = {
        column.key: _as_json(getattr(person, column.key)) for column in Person.__table__.columns
    }
    data["emails"] = _card(db, person).emails
    return data


def _later(first: datetime | None, second: datetime | None) -> datetime | None:
    """The later of two optional times."""
    if first is None or second is None:
        return first or second
    return max(first, second)


def _apply_choices(
    survivor: Person, absorbed: Person, values: Mapping[str, str | None]
) -> list[str]:
    """Set each field on the survivor: the reviewer's non-blank choice, else the latest value.

    Blank choices never erase data (D-046). Returns the names of the fields that changed.
    """
    people: dict[Side, Person] = {"a": survivor, "b": absorbed}
    changed: list[str] = []
    for field in MERGE_FIELDS:
        chosen = values.get(field)
        if _blank(chosen):
            chosen = getattr(people[suggest_side(survivor, absorbed, field)], field)
        if not _blank(chosen) and getattr(survivor, field) != chosen:
            setattr(survivor, field, chosen.strip() if isinstance(chosen, str) else chosen)
            changed.append(field)
    return changed


def _combine_aggregates(survivor: Person, absorbed: Person) -> None:
    """Combine the fields that have one obvious merged answer (no reviewer choice needed)."""
    survivor.last_contacted_at = _later(survivor.last_contacted_at, absorbed.last_contacted_at)
    survivor.replied_at = _later(survivor.replied_at, absorbed.replied_at)
    survivor.email_bounced = survivor.email_bounced or absorbed.email_bounced
    survivor.lists = list(dict.fromkeys([*survivor.lists, *absorbed.lists]))
    for field in ("company_id", "owner_id", "intent_signals", "qualify_contact"):
        if getattr(survivor, field) is None:
            setattr(survivor, field, getattr(absorbed, field))


def _person_fk_columns(table: Table) -> list[Column]:
    """The columns of a table that are foreign keys to people.id."""
    return [
        column
        for column in table.columns
        if any(fk.column.table.name == Person.__tablename__ for fk in column.foreign_keys)
    ]


def _delete_clashes(
    db: Session, table: Table, column: Column, absorbed_id: uuid.UUID, survivor_id: uuid.UUID
) -> None:
    """Delete absorbed rows that would duplicate a survivor row under a unique constraint."""
    for constraint in table.constraints:
        if not isinstance(constraint, UniqueConstraint) or column.name not in constraint.columns:
            continue
        others = [c for c in constraint.columns if c.name != column.name]
        twin = table.alias()
        same_values = [twin.c[c.name] == table.c[c.name] for c in others]
        db.execute(
            delete(table).where(
                column == absorbed_id,
                exists().where(twin.c[column.name] == survivor_id, *same_values),
            )
        )


def _move_children(db: Session, absorbed_id: uuid.UUID, survivor_id: uuid.UUID) -> None:
    """Point every row that belongs to the absorbed person at the survivor.

    Done from the table metadata, so a table that references people (touches, events, notes,
    flags, campaign leads, mail threads, outreach messages, raw rows, merge records) is covered
    without leads importing the modules built after it. Rows that would clash with a unique
    constraint are dropped first; only one primary email per person is allowed, so the
    absorbed addresses arrive as non-primary.
    """
    db.execute(
        update(PersonEmail.__table__)
        .where(PersonEmail.__table__.c.person_id == absorbed_id)
        .values(is_primary=False)
    )
    for table in Base.metadata.sorted_tables:
        if table.name in _SKIPPED_TABLES:
            continue
        for column in _person_fk_columns(table):
            _delete_clashes(db, table, column, absorbed_id, survivor_id)
            db.execute(update(table).where(column == absorbed_id).values({column.key: survivor_id}))


def _repoint_other_pairs(
    db: Session, merged: DuplicateCandidate, absorbed_id: uuid.UUID, survivor_id: uuid.UUID
) -> None:
    """Move the absorbed person's other open or decided pairs onto the survivor.

    A pair that would become a self-pair, or that the survivor already has, is dropped.
    """
    others = db.scalars(
        select(DuplicateCandidate).where(
            or_(
                DuplicateCandidate.person_a_id == absorbed_id,
                DuplicateCandidate.person_b_id == absorbed_id,
            ),
            DuplicateCandidate.id != merged.id,
        )
    ).all()
    for pair in others:
        other_id = pair.person_b_id if pair.person_a_id == absorbed_id else pair.person_a_id
        if other_id == survivor_id or find_duplicate_decision(db, survivor_id, other_id):
            db.delete(pair)
        else:
            pair.person_a_id, pair.person_b_id = sorted((survivor_id, other_id))
        db.flush()


def merge_candidate(
    db: Session,
    actor: User,
    candidate_id: uuid.UUID,
    *,
    survivor_id: uuid.UUID,
    values: Mapping[str, str | None],
    ip_address: str | None = None,
) -> MergeRecord:
    """Merge the two people of an open pair into the survivor (D-108).

    Args:
        survivor_id: The person to keep; the other is absorbed and deleted.
        values: The reviewer's choice per field, keyed by Person column name. A field left
            out or blank gets the most recent non-blank value.

    Returns:
        The MergeRecord holding the snapshot of the absorbed person.

    Raises:
        DuplicateNotFoundError: If the pair does not exist.
        DuplicateNotOpenError: If it was already decided.
        DuplicateSurvivorError: If survivor_id is not one of the two people.
        DuplicateFieldError: If values names a field that cannot be merged.
    """
    unknown = sorted(set(values) - set(MERGE_FIELDS))
    if unknown:
        raise DuplicateFieldError(", ".join(unknown))
    candidate = _lock_open(db, candidate_id)
    pair_ids = {candidate.person_a_id, candidate.person_b_id}
    if survivor_id not in pair_ids:
        raise DuplicateSurvivorError
    absorbed_id = next(iter(pair_ids - {survivor_id}))
    survivor = db.get(Person, survivor_id, with_for_update=True)
    absorbed = db.get(Person, absorbed_id, with_for_update=True)
    assert survivor is not None and absorbed is not None  # both ids are foreign keys

    snapshot = _snapshot(db, absorbed)
    changed_fields = _apply_choices(survivor, absorbed, values)
    _combine_aggregates(survivor, absorbed)
    db.flush()

    # The pair row is deleted with the absorbed person (CASCADE); the MergeRecord and the
    # audit event are what remain of the decision.
    _repoint_other_pairs(db, candidate, absorbed_id, survivor_id)
    _move_children(db, absorbed_id, survivor_id)
    merge_record = MergeRecord(
        survivor_id=survivor_id,
        absorbed_person_id=absorbed_id,
        snapshot=snapshot,
        merged_by=actor.id,
    )
    db.add(merge_record)
    db.add(
        LeadEvent(
            person_id=survivor_id,
            event_type=PERSON_MERGED_EVENT,
            detail={"absorbed_person_id": str(absorbed_id), "fields": changed_fields},
            actor_id=actor.id,
        )
    )
    # Remove the pair row ourselves (the absorbed person would cascade it anyway), so the
    # caller's copy of it stays readable after the commit.
    db.delete(candidate)
    db.flush()
    db.expire_all()
    db.delete(db.get(Person, absorbed_id))
    record(
        db,
        action=AuditAction.DUPLICATE_MERGED,
        actor_user_id=actor.id,
        object_type=AUDIT_OBJECT_TYPE,
        object_id=str(candidate_id),
        summary={
            "survivor_id": str(survivor_id),
            "absorbed_person_id": str(absorbed_id),
            "fields_changed": changed_fields,
        },
        ip_address=ip_address,
    )
    db.commit()
    return merge_record
