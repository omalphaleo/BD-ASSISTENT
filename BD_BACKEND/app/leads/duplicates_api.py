"""Duplicate review routes under /duplicates (M2-B5, D-092, D-108).

Needed so a manager or admin can list possible duplicate pairs, merge two people or mark a
pair "not a duplicate". Thin handlers: the rules live in leads.duplicates. Every route needs
REVIEW_DUPLICATES (manager and admin); the service audits each decision. Errors use fixed
messages and never echo submitted values.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.models import User
from app.core.permissions import Permission, require_permission
from app.db import get_session
from app.leads import duplicates
from app.leads.duplicate_schemas import (
    DuplicateCandidateResponse,
    DuplicateListResponse,
    DuplicateStatusFilter,
    MergeDuplicateRequest,
    MergeDuplicateResponse,
)
from app.leads.duplicates import (
    DuplicateFieldError,
    DuplicateNotFoundError,
    DuplicateNotOpenError,
    DuplicateSurvivorError,
)

router = APIRouter(prefix="/duplicates", tags=["duplicates"])

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

NOT_FOUND_DETAIL = "Duplicate pair not found"
NOT_OPEN_DETAIL = "This pair was already decided."
SURVIVOR_DETAIL = "The person to keep must be one of the two people in the pair."
FIELD_DETAIL = "A value names a field that cannot be merged."

Db = Annotated[Session, Depends(get_session)]
Reviewer = Annotated[User, Depends(require_permission(Permission.REVIEW_DUPLICATES))]


def _client_ip(request: Request) -> str | None:
    """Client address for the audit event, if known."""
    return request.client.host if request.client else None


def _error(status_code: int, detail: str) -> JSONResponse:
    """A fixed-message error body; nothing from the records is echoed back."""
    return JSONResponse(status_code=status_code, content={"detail": detail})


@router.get("", response_model=DuplicateListResponse)
def list_duplicates(
    _actor: Reviewer,
    db: Db,
    status_filter: Annotated[DuplicateStatusFilter, Query(alias="status")] = (
        DuplicateStatusFilter.OPEN
    ),
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Any:
    """List duplicate pairs, longest-waiting first."""
    views, total = duplicates.list_candidates(
        db, status=status_filter.to_status(), limit=limit, offset=offset
    )
    return DuplicateListResponse(
        items=[DuplicateCandidateResponse.from_view(view) for view in views],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{candidate_id}",
    response_model=DuplicateCandidateResponse,
    responses={404: {"description": "No such pair."}},
)
def get_duplicate(candidate_id: uuid.UUID, _actor: Reviewer, db: Db) -> Any:
    """Return one pair with both people and the suggested side per field."""
    try:
        view = duplicates.get_candidate(db, candidate_id)
    except DuplicateNotFoundError:
        return _error(status.HTTP_404_NOT_FOUND, NOT_FOUND_DETAIL)
    return DuplicateCandidateResponse.from_view(view)


@router.post(
    "/{candidate_id}/merge",
    response_model=MergeDuplicateResponse,
    responses={
        404: {"description": "No such pair."},
        409: {"description": "The pair was already decided."},
        422: {"description": "Bad survivor or field name."},
    },
)
def merge_duplicate(
    candidate_id: uuid.UUID, body: MergeDuplicateRequest, request: Request, actor: Reviewer, db: Db
) -> Any:
    """Merge the pair into the chosen survivor, keeping every email and all history."""
    try:
        merge_record = duplicates.merge_candidate(
            db,
            actor,
            candidate_id,
            survivor_id=body.survivor_id,
            values=body.values,
            ip_address=_client_ip(request),
        )
    except DuplicateNotFoundError:
        return _error(status.HTTP_404_NOT_FOUND, NOT_FOUND_DETAIL)
    except DuplicateNotOpenError:
        return _error(status.HTTP_409_CONFLICT, NOT_OPEN_DETAIL)
    except DuplicateSurvivorError:
        return _error(422, SURVIVOR_DETAIL)
    except DuplicateFieldError:
        return _error(422, FIELD_DETAIL)
    return MergeDuplicateResponse(
        survivor_id=merge_record.survivor_id,
        absorbed_person_id=merge_record.absorbed_person_id,
        merge_record_id=merge_record.id,
    )


@router.post(
    "/{candidate_id}/not-duplicate",
    response_model=DuplicateCandidateResponse,
    responses={
        404: {"description": "No such pair."},
        409: {"description": "The pair was already decided."},
    },
)
def mark_not_duplicate(candidate_id: uuid.UUID, request: Request, actor: Reviewer, db: Db) -> Any:
    """Record that the two people are different; the pair is never raised again."""
    try:
        view = duplicates.mark_not_duplicate(
            db, actor, candidate_id, ip_address=_client_ip(request)
        )
    except DuplicateNotFoundError:
        return _error(status.HTTP_404_NOT_FOUND, NOT_FOUND_DETAIL)
    except DuplicateNotOpenError:
        return _error(status.HTTP_409_CONFLICT, NOT_OPEN_DETAIL)
    return DuplicateCandidateResponse.from_view(view)
