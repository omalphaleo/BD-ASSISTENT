"""Quarantine routes under /quarantine: list, view, fix, release and discard (M2-B2).

Needed so BD can review import rows held for a problem (D-068), correct them, and either
release them into the lead database or discard them (D-107). Thin handlers: the rules live in
leads.quarantine. Fix and release need FIX_QUARANTINE (any BD user); discard needs
DISCARD_QUARANTINE and the service then checks the importer-or-manager rule. Every state
change is audited by the service.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.models import User
from app.core.permissions import Permission, require_permission
from app.db import get_session
from app.leads import quarantine
from app.leads.contracts import IngestRow
from app.leads.ingest import ingest_row
from app.leads.quarantine import (
    IngestUnavailableError,
    QuarantineFieldError,
    QuarantineNotFoundError,
    QuarantineNotOpenError,
    QuarantineNotReleasableError,
)
from app.leads.schemas import (
    FixQuarantineRequest,
    QuarantineListResponse,
    QuarantineRecordResponse,
    QuarantineStatusFilter,
    ReleaseQuarantineResponse,
)
from app.leads.validation import RowIssue

router = APIRouter(prefix="/quarantine", tags=["quarantine"])

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

NOT_FOUND_DETAIL = "Quarantine record not found"
NOT_OPEN_DETAIL = "This record was already released or discarded."
NOT_RELEASABLE_DETAIL = "This record has no source row, so it cannot be released."
INGEST_UNAVAILABLE_DETAIL = "Releasing valid rows is not available yet."

Db = Annotated[Session, Depends(get_session)]
Fixer = Annotated[User, Depends(require_permission(Permission.FIX_QUARANTINE))]
Discarder = Annotated[User, Depends(require_permission(Permission.DISCARD_QUARANTINE))]


def get_release_ingest_row() -> IngestRow:
    """Return the ingest_row that release uses: the same function an import calls (D-107).

    A test can replace this dependency with a fake. IngestUnavailableError is still mapped to
    503 below for any stand-in that refuses.
    """
    return ingest_row


ReleaseIngest = Annotated[IngestRow, Depends(get_release_ingest_row)]


def _client_ip(request: Request) -> str | None:
    """Client address for the audit event, if known."""
    return request.client.host if request.client else None


def _error(status_code: int, detail: str) -> JSONResponse:
    """A fixed-message error body; nothing from the row is ever echoed back."""
    return JSONResponse(status_code=status_code, content={"detail": detail})


@router.get("", response_model=QuarantineListResponse)
def list_quarantine(
    _actor: Fixer,
    db: Db,
    status_filter: Annotated[QuarantineStatusFilter, Query(alias="status")] = (
        QuarantineStatusFilter.OPEN
    ),
    issue: Annotated[RowIssue | None, Query(description="Only rows with this reason code")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Any:
    """List quarantined rows, newest first. Any BD user sees every record (D-107)."""
    items, total = quarantine.list_items(
        db, status=status_filter.to_status(), issue=issue, limit=limit, offset=offset
    )
    return QuarantineListResponse(
        items=[QuarantineRecordResponse.from_item(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{record_id}",
    response_model=QuarantineRecordResponse,
    responses={404: {"description": "No such quarantine record."}},
)
def get_quarantine_record(record_id: uuid.UUID, _actor: Fixer, db: Db) -> Any:
    """Return one quarantined row with its source file and row number."""
    try:
        item = quarantine.get_item(db, record_id)
    except QuarantineNotFoundError:
        return _error(status.HTTP_404_NOT_FOUND, NOT_FOUND_DETAIL)
    return QuarantineRecordResponse.from_item(item)


@router.patch(
    "/{record_id}",
    response_model=QuarantineRecordResponse,
    responses={
        404: {"description": "No such quarantine record."},
        409: {"description": "Already released or discarded."},
        422: {"description": "A field name or value is not acceptable."},
    },
)
def fix_quarantine_record(
    record_id: uuid.UUID, body: FixQuarantineRequest, request: Request, actor: Fixer, db: Db
) -> Any:
    """Edit an open record (for example add a work email); its reason codes are refreshed."""
    try:
        item = quarantine.fix_item(
            db, actor, record_id, body.values, ip_address=_client_ip(request)
        )
    except QuarantineNotFoundError:
        return _error(status.HTTP_404_NOT_FOUND, NOT_FOUND_DETAIL)
    except QuarantineNotOpenError:
        return _error(status.HTTP_409_CONFLICT, NOT_OPEN_DETAIL)
    except QuarantineFieldError as error:
        return _error(422, str(error))
    return QuarantineRecordResponse.from_item(item)


@router.post(
    "/{record_id}/release",
    response_model=ReleaseQuarantineResponse,
    responses={
        404: {"description": "No such quarantine record."},
        409: {"description": "Already released or discarded, or it has no source row."},
        503: {"description": "Row is valid but ingest_row is not available yet."},
    },
)
def release_quarantine_record(
    record_id: uuid.UUID, request: Request, actor: Fixer, db: Db, ingest_row: ReleaseIngest
) -> Any:
    """Revalidate and release a record. "released": false means it stays open with its reasons."""
    try:
        result = quarantine.release_item(
            db, actor, record_id, ingest_row, ip_address=_client_ip(request)
        )
    except QuarantineNotFoundError:
        return _error(status.HTTP_404_NOT_FOUND, NOT_FOUND_DETAIL)
    except QuarantineNotOpenError:
        return _error(status.HTTP_409_CONFLICT, NOT_OPEN_DETAIL)
    except QuarantineNotReleasableError:
        return _error(status.HTTP_409_CONFLICT, NOT_RELEASABLE_DETAIL)
    except IngestUnavailableError:
        db.rollback()
        return _error(status.HTTP_503_SERVICE_UNAVAILABLE, INGEST_UNAVAILABLE_DETAIL)
    return ReleaseQuarantineResponse.from_result(result)


@router.post(
    "/{record_id}/discard",
    response_model=QuarantineRecordResponse,
    responses={
        404: {"description": "No such quarantine record."},
        409: {"description": "Already released or discarded."},
    },
)
def discard_quarantine_record(
    record_id: uuid.UUID, request: Request, actor: Discarder, db: Db
) -> Any:
    """Discard an open record. Only the importer, a manager or an admin may (D-107)."""
    try:
        item = quarantine.discard_item(db, actor, record_id, ip_address=_client_ip(request))
    except QuarantineNotFoundError:
        return _error(status.HTTP_404_NOT_FOUND, NOT_FOUND_DETAIL)
    except QuarantineNotOpenError:
        return _error(status.HTTP_409_CONFLICT, NOT_OPEN_DETAIL)
    return QuarantineRecordResponse.from_item(item)
