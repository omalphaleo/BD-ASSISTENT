"""Saved segment routes under /segments: list, save, rename or share, delete (M3-A4).

Needed so the search page can save a filter combination and reuse it (D-009), private by default
and shareable with the team (D-098). Thin handlers: the rules live in leads.segments. Reading
needs VIEW_ALL_LEADS and writing needs CREATE_SEGMENT (every BD user); who may change a given
segment is checked again in the service. Errors use fixed messages and never echo what was sent.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.models import User
from app.core.permissions import Permission, require_permission
from app.db import get_session
from app.leads import segments
from app.leads.segment_schemas import (
    SegmentCreate,
    SegmentListResponse,
    SegmentResponse,
    SegmentUpdate,
)
from app.leads.segments import SegmentNotFoundError

router = APIRouter(prefix="/segments", tags=["segments"])

NOT_FOUND_DETAIL = "Segment not found"

Db = Annotated[Session, Depends(get_session)]
Viewer = Annotated[User, Depends(require_permission(Permission.VIEW_ALL_LEADS))]
Author = Annotated[User, Depends(require_permission(Permission.CREATE_SEGMENT))]


def _client_ip(request: Request) -> str | None:
    """Client address for the audit event, if known."""
    return request.client.host if request.client else None


def _not_found() -> JSONResponse:
    """A fixed-message 404; the same body for a missing and for a private segment."""
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": NOT_FOUND_DETAIL})


@router.get("", response_model=SegmentListResponse)
def list_segments(viewer: Viewer, db: Db) -> SegmentListResponse:
    """List the caller's own segments and every segment shared with the team."""
    return segments.list_segments(db, viewer)


@router.post("", response_model=SegmentResponse, status_code=status.HTTP_201_CREATED)
def create_segment(
    body: SegmentCreate, request: Request, author: Author, db: Db
) -> SegmentResponse:
    """Save the given filters as a segment owned by the caller (private unless shared)."""
    return segments.create_segment(db, author, body, ip_address=_client_ip(request))


@router.patch(
    "/{segment_id}",
    response_model=SegmentResponse,
    responses={
        403: {"description": "A shared segment owned by someone else."},
        404: {"description": "No such segment, or someone else's private one."},
    },
)
def update_segment(
    segment_id: uuid.UUID, body: SegmentUpdate, request: Request, author: Author, db: Db
) -> Any:
    """Rename a segment and/or share or unshare it (owner only; admin if it has no owner)."""
    try:
        return segments.update_segment(db, author, segment_id, body, ip_address=_client_ip(request))
    except SegmentNotFoundError:
        return _not_found()


@router.delete(
    "/{segment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,  # a 204 has no body; the 404 path returns its own JSON response
    responses={
        403: {"description": "A shared segment owned by someone else."},
        404: {"description": "No such segment, or someone else's private one."},
    },
)
def delete_segment(segment_id: uuid.UUID, request: Request, author: Author, db: Db) -> Any:
    """Delete a segment (owner only; admin if it has no owner)."""
    try:
        segments.delete_segment(db, author, segment_id, ip_address=_client_ip(request))
    except SegmentNotFoundError:
        return _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
