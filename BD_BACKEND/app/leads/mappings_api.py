"""Industry and state mapping routes under /reference-mappings (M2-B6, D-076, D-104).

Needed so an admin can list, add and edit the mappings that tidy imported industries and
states. Thin handlers: the rules live in leads.mappings. Every route needs
MANAGE_SOURCE_PROFILES (admin only); each change is audited by the service. Errors use fixed
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
from app.leads import mappings
from app.leads.mapping_schemas import (
    CreateIndustryMappingRequest,
    CreateStateMappingRequest,
    IndustryMappingListResponse,
    IndustryMappingResponse,
    StateMappingListResponse,
    StateMappingResponse,
    UpdateIndustryMappingRequest,
    UpdateStateMappingRequest,
)
from app.leads.mappings import MappingExistsError, MappingNotFoundError, MappingValueError

router = APIRouter(prefix="/reference-mappings", tags=["reference-mappings"])

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

NOT_FOUND_DETAIL = "Mapping not found"
EXISTS_DETAIL = "A mapping for this wording already exists."
BLANK_DETAIL = "A required value must not be blank."

Db = Annotated[Session, Depends(get_session)]
Admin = Annotated[User, Depends(require_permission(Permission.MANAGE_SOURCE_PROFILES))]
Search = Annotated[str | None, Query(max_length=255, description="Text inside the wording")]
Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
Offset = Annotated[int, Query(ge=0)]


def _client_ip(request: Request) -> str | None:
    """Client address for the audit event, if known."""
    return request.client.host if request.client else None


def _error(status_code: int, detail: str) -> JSONResponse:
    """A fixed-message error body."""
    return JSONResponse(status_code=status_code, content={"detail": detail})


_WRITE_ERRORS = {
    404: {"description": "No such mapping."},
    409: {"description": "That wording already has a mapping."},
    422: {"description": "A required value is blank."},
}


def _failure(error: Exception) -> JSONResponse:
    """Map a service error to its fixed response."""
    if isinstance(error, MappingNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, NOT_FOUND_DETAIL)
    if isinstance(error, MappingExistsError):
        return _error(status.HTTP_409_CONFLICT, EXISTS_DETAIL)
    return _error(422, BLANK_DETAIL)


_ERRORS = (MappingNotFoundError, MappingExistsError, MappingValueError)


@router.get("/industries", response_model=IndustryMappingListResponse)
def list_industry_mappings(
    _actor: Admin,
    db: Db,
    search: Search = None,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> Any:
    """List industry mappings by source wording."""
    rows, total = mappings.list_industry_mappings(db, search=search, limit=limit, offset=offset)
    return IndustryMappingListResponse(
        items=[IndustryMappingResponse.from_row(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/industries",
    response_model=IndustryMappingResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_WRITE_ERRORS,
)
def create_industry_mapping(
    body: CreateIndustryMappingRequest, request: Request, actor: Admin, db: Db
) -> Any:
    """Add an industry mapping; the wording is stored lowercase."""
    try:
        row = mappings.create_industry_mapping(
            db, actor, **body.model_dump(), ip_address=_client_ip(request)
        )
    except _ERRORS as error:
        return _failure(error)
    return IndustryMappingResponse.from_row(row)


@router.patch(
    "/industries/{mapping_id}", response_model=IndustryMappingResponse, responses=_WRITE_ERRORS
)
def update_industry_mapping(
    mapping_id: uuid.UUID,
    body: UpdateIndustryMappingRequest,
    request: Request,
    actor: Admin,
    db: Db,
) -> Any:
    """Edit an industry mapping; only the fields sent are changed."""
    try:
        row = mappings.update_industry_mapping(
            db,
            actor,
            mapping_id,
            body.model_dump(exclude_unset=True),
            ip_address=_client_ip(request),
        )
    except _ERRORS as error:
        return _failure(error)
    return IndustryMappingResponse.from_row(row)


@router.get("/states", response_model=StateMappingListResponse)
def list_state_mappings(
    _actor: Admin,
    db: Db,
    search: Search = None,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> Any:
    """List state mappings by country and source wording."""
    rows, total = mappings.list_state_mappings(db, search=search, limit=limit, offset=offset)
    return StateMappingListResponse(
        items=[StateMappingResponse.from_row(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/states",
    response_model=StateMappingResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_WRITE_ERRORS,
)
def create_state_mapping(
    body: CreateStateMappingRequest, request: Request, actor: Admin, db: Db
) -> Any:
    """Add a state mapping; the wording is stored lowercase."""
    try:
        row = mappings.create_state_mapping(
            db, actor, **body.model_dump(), ip_address=_client_ip(request)
        )
    except _ERRORS as error:
        return _failure(error)
    return StateMappingResponse.from_row(row)


@router.patch("/states/{mapping_id}", response_model=StateMappingResponse, responses=_WRITE_ERRORS)
def update_state_mapping(
    mapping_id: uuid.UUID,
    body: UpdateStateMappingRequest,
    request: Request,
    actor: Admin,
    db: Db,
) -> Any:
    """Edit a state mapping; only the fields sent are changed."""
    try:
        row = mappings.update_state_mapping(
            db,
            actor,
            mapping_id,
            body.model_dump(exclude_unset=True),
            ip_address=_client_ip(request),
        )
    except _ERRORS as error:
        return _failure(error)
    return StateMappingResponse.from_row(row)
