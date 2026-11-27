"""Saved segments: save, list, rename, share and delete a named filter (M3-A4, D-009, D-098).

Needed so a rep can reuse a filter combination instead of rebuilding it, privately by default or
shared with the team. The routes in segments_api.py are thin wrappers; every rule (who sees a
segment, who changes it, what is audited) lives here and is re-checked on each call.
"""

import logging
import uuid
from collections.abc import Mapping

from pydantic import ValidationError
from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from app.audit.services import AuditAction, record
from app.core.models import User, UserRole
from app.core.permissions import PermissionDeniedError, is_owner
from app.leads.filters import FilterSet
from app.leads.models import Segment, SegmentVisibility
from app.leads.segment_schemas import (
    SegmentCreate,
    SegmentListResponse,
    SegmentOwner,
    SegmentResponse,
    SegmentUpdate,
)

logger = logging.getLogger(__name__)

AUDIT_OBJECT_TYPE = "segment"


class SegmentNotFoundError(Exception):
    """The segment does not exist, or the caller may not even know it exists.

    Another rep's private segment looks exactly like a missing one, so its existence and name
    are not leaked (Decision 3 of the M3-A4 plan).
    """


def _is_ownerless(segment: Segment) -> bool:
    """True when the owner's user row was deleted (owner_id is SET NULL)."""
    return segment.owner_id is None


def _can_see(actor: User, segment: Segment) -> bool:
    """Whether the actor may know the segment exists.

    Own segments and shared segments are visible. An ownerless segment is visible to admins
    only, so they can clean it up (Decision 2); nobody's private list is ever exposed by this.
    """
    return (
        is_owner(actor, segment.owner_id)
        or segment.visibility is SegmentVisibility.SHARED
        or (_is_ownerless(segment) and actor.role is UserRole.ADMIN)
    )


def _can_edit(actor: User, segment: Segment) -> bool:
    """Whether the actor may rename, share or delete the segment (D-098, Decision 2).

    The owner may. An admin may only when the segment has no owner, never when a live rep owns
    it, so an admin cannot silently change a rep's list.
    """
    return is_owner(actor, segment.owner_id) or (
        _is_ownerless(segment) and actor.role is UserRole.ADMIN
    )


def _to_response(segment: Segment, owner: User | None, actor: User) -> SegmentResponse:
    """Build the API shape, validating the stored filters again (Decision 5).

    Stored JSON can outlive the FilterSet that wrote it. A row that no longer validates is
    still returned with filters_valid=False so one stale row never breaks the whole list.
    """
    filters: FilterSet | None
    try:
        filters = FilterSet.model_validate(segment.filters)
    except ValidationError:
        # Log the id only: the stored filters can contain typed search terms.
        logger.warning("segment_filters_invalid", extra={"segment_id": str(segment.id)})
        filters = None
    return SegmentResponse(
        id=segment.id,
        name=segment.name,
        visibility=segment.visibility,
        owner=SegmentOwner(id=owner.id, email=owner.email) if owner else None,
        can_edit=_can_edit(actor, segment),
        filters_valid=filters is not None,
        filters=filters,
        created_at=segment.created_at,
        updated_at=segment.updated_at,
    )


def _load_visible(db: Session, actor: User, segment_id: uuid.UUID) -> Segment:
    """Load a segment the actor may see.

    Raises:
        SegmentNotFoundError: no such segment, or it is someone else's private segment.
    """
    segment = db.get(Segment, segment_id)
    if segment is None or not _can_see(actor, segment):
        raise SegmentNotFoundError
    return segment


def _load_editable(db: Session, actor: User, segment_id: uuid.UUID) -> Segment:
    """Load a segment the actor may change.

    Raises:
        SegmentNotFoundError: no such segment, or the actor may not see it.
        PermissionDeniedError: the actor can see it (shared) but does not own it.
    """
    segment = _load_visible(db, actor, segment_id)
    if not _can_edit(actor, segment):
        raise PermissionDeniedError
    return segment


def _audit(
    db: Session,
    action: AuditAction,
    actor: User,
    segment: Segment,
    ip_address: str | None,
    extra: Mapping[str, object] | None = None,
) -> None:
    """Write one audit row. The summary never holds filter values (they may be search terms)."""
    record(
        db,
        action=action,
        actor_user_id=actor.id,
        object_type=AUDIT_OBJECT_TYPE,
        object_id=str(segment.id),
        summary={"name": segment.name, "visibility": segment.visibility.value, **(extra or {})},
        ip_address=ip_address,
    )


def list_segments(db: Session, actor: User) -> SegmentListResponse:
    """Return the actor's own segments and every shared one, ordered by name.

    Admins also see ownerless segments, so they can delete them (Decision 2).
    """
    visible = or_(
        Segment.owner_id == actor.id,
        Segment.visibility == SegmentVisibility.SHARED,
        # An admin sees ownerless rows; for everyone else this clause is always false.
        Segment.owner_id.is_(None) if actor.role is UserRole.ADMIN else false(),
    )
    rows = db.execute(
        select(Segment, User)
        .outerjoin(User, User.id == Segment.owner_id)
        .where(visible)
        .order_by(func.lower(Segment.name), Segment.created_at, Segment.id)
    ).all()
    return SegmentListResponse(items=[_to_response(row[0], row[1], actor) for row in rows])


def create_segment(
    db: Session, actor: User, data: SegmentCreate, *, ip_address: str | None = None
) -> SegmentResponse:
    """Save a segment owned by the actor, private unless asked to share (D-098).

    Duplicate names are allowed (Decision 4); the list shows the owner to tell them apart.
    """
    segment = Segment(
        name=data.name,
        # The same JSON form the search request uses, so a stored filter replays identically.
        filters=data.filters.model_dump(mode="json"),
        visibility=data.visibility,
        owner_id=actor.id,
    )
    db.add(segment)
    db.flush()
    _audit(db, AuditAction.SEGMENT_CREATED, actor, segment, ip_address)
    db.commit()
    return _to_response(segment, actor, actor)


def update_segment(
    db: Session,
    actor: User,
    segment_id: uuid.UUID,
    data: SegmentUpdate,
    *,
    ip_address: str | None = None,
) -> SegmentResponse:
    """Rename and/or share or unshare a segment. Sharing is a visibility change (Decision 1).

    Nothing is written or audited when the request changes nothing.

    Raises:
        SegmentNotFoundError: no such segment, or it is someone else's private segment.
        PermissionDeniedError: the segment is shared but the actor may not change it.
    """
    segment = _load_editable(db, actor, segment_id)
    changed: list[str] = []
    if data.name is not None and data.name != segment.name:
        segment.name = data.name
        changed.append("name")
    if data.visibility is not None and data.visibility is not segment.visibility:
        segment.visibility = data.visibility
        changed.append("visibility")
    if changed:
        db.flush()
        _audit(db, AuditAction.SEGMENT_UPDATED, actor, segment, ip_address, {"changed": changed})
        db.commit()
    owner = db.get(User, segment.owner_id) if segment.owner_id else None
    return _to_response(segment, owner, actor)


def delete_segment(
    db: Session, actor: User, segment_id: uuid.UUID, *, ip_address: str | None = None
) -> None:
    """Delete a segment.

    Raises:
        SegmentNotFoundError: no such segment, or it is someone else's private segment.
        PermissionDeniedError: the segment is shared but the actor may not delete it.
    """
    segment = _load_editable(db, actor, segment_id)
    # Audit first: the row (and so its name) is gone after the delete.
    _audit(db, AuditAction.SEGMENT_DELETED, actor, segment, ip_address)
    db.delete(segment)
    db.commit()
