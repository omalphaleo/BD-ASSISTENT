"""Source profile admin routes under /source-profiles (M2-A6).

Needed so admins can list, create, edit, deactivate and trim the saved mapping of source
profiles from the admin page. Every route requires MANAGE_SOURCE_PROFILES (admins only, D-049,
D-104). Thin handlers: the rules (case-insensitive unique names, warnings, audit) are in
imports.profiles. Profiles are never deleted; the uploader's picker lives in imports.mapping_api.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.models import User
from app.core.permissions import Permission, require_permission
from app.db import get_session
from app.imports.errors import ProfileErrorKind, ProfileRejectedError
from app.imports.models import SourceProfile
from app.imports.profiles import (
    create_profile,
    get_profile,
    list_profiles,
    remove_default_columns,
    saved_columns,
    update_profile,
)
from app.imports.schemas import (
    CreateSourceProfileRequest,
    ProfileErrorResponse,
    RemoveProfileColumnsRequest,
    SourceProfileDetailResponse,
    SourceProfileResponse,
    UpdateSourceProfileRequest,
)

router = APIRouter(prefix="/source-profiles", tags=["source-profiles"])

# HTTP status per refusal kind. 409: conflicts with current data; 422: the request is not usable.
PROFILE_ERROR_STATUS: dict[ProfileErrorKind, int] = {
    ProfileErrorKind.NOT_FOUND: 404,
    ProfileErrorKind.DUPLICATE_NAME: 409,
    ProfileErrorKind.INVALID_DEFAULTS: 409,
    ProfileErrorKind.UNKNOWN_COLUMN: 422,
}
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ProfileErrorResponse, "description": "No such source profile."},
    409: {"model": ProfileErrorResponse, "description": "Name taken or saved mapping invalid."},
    422: {"model": ProfileErrorResponse, "description": "The request is not usable."},
}

Db = Annotated[Session, Depends(get_session)]
ProfileAdmin = Annotated[User, Depends(require_permission(Permission.MANAGE_SOURCE_PROFILES))]


def _client_ip(request: Request) -> str | None:
    """Client address for the audit event, if known."""
    return request.client.host if request.client else None


def _refused(error: ProfileRejectedError) -> JSONResponse:
    """Turn a refused profile request into its 4xx response (fixed message only)."""
    body = ProfileErrorResponse(detail=error.message, code=error.kind.value)
    return JSONResponse(status_code=PROFILE_ERROR_STATUS[error.kind], content=body.model_dump())


def _summary(profile: SourceProfile) -> SourceProfileResponse:
    """The list shape of a profile."""
    columns = saved_columns(profile)
    return SourceProfileResponse(
        id=profile.id,
        name=profile.name,
        layout=profile.layout,
        is_active=profile.is_active,
        saved_column_count=len(columns or {}),
        defaults_valid=columns is not None,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _detail(
    profile: SourceProfile, warnings: list[str] | None = None
) -> SourceProfileDetailResponse:
    """The detail shape: the list shape plus the saved header -> field map."""
    return SourceProfileDetailResponse(
        **_summary(profile).model_dump(),
        columns=saved_columns(profile) or {},
        warnings=warnings or [],
    )


@router.get("", response_model=list[SourceProfileResponse])
def list_source_profiles(_actor: ProfileAdmin, db: Db) -> Any:
    """Every source profile, active and inactive."""
    return [_summary(profile) for profile in list_profiles(db)]


@router.post(
    "",
    response_model=SourceProfileDetailResponse,
    status_code=201,
    responses=ERROR_RESPONSES,
)
def create_source_profile(
    body: CreateSourceProfileRequest, request: Request, actor: ProfileAdmin, db: Db
) -> Any:
    """Create an active profile with no saved mapping."""
    try:
        profile = create_profile(
            db, actor, name=body.name, layout=body.layout, ip_address=_client_ip(request)
        )
    except ProfileRejectedError as error:
        return _refused(error)
    return _detail(profile)


@router.get("/{profile_id}", response_model=SourceProfileDetailResponse, responses=ERROR_RESPONSES)
def read_source_profile(profile_id: uuid.UUID, _actor: ProfileAdmin, db: Db) -> Any:
    """One profile with its saved header -> field map."""
    try:
        return _detail(get_profile(db, profile_id))
    except ProfileRejectedError as error:
        return _refused(error)


@router.patch(
    "/{profile_id}", response_model=SourceProfileDetailResponse, responses=ERROR_RESPONSES
)
def edit_source_profile(
    profile_id: uuid.UUID,
    body: UpdateSourceProfileRequest,
    request: Request,
    actor: ProfileAdmin,
    db: Db,
) -> Any:
    """Rename, relabel, activate or deactivate a profile; deactivation may carry a warning."""
    try:
        result = update_profile(
            db,
            actor,
            profile_id,
            name=body.name,
            layout=body.layout,
            is_active=body.is_active,
            ip_address=_client_ip(request),
        )
    except ProfileRejectedError as error:
        return _refused(error)
    return _detail(result.profile, result.warnings)


@router.post(
    "/{profile_id}/remove-columns",
    response_model=SourceProfileDetailResponse,
    responses=ERROR_RESPONSES,
)
def remove_source_profile_columns(
    profile_id: uuid.UUID,
    body: RemoveProfileColumnsRequest,
    request: Request,
    actor: ProfileAdmin,
    db: Db,
) -> Any:
    """Forget saved header mappings of a profile."""
    try:
        profile = remove_default_columns(
            db, actor, profile_id, body.headers, ip_address=_client_ip(request)
        )
    except ProfileRejectedError as error:
        return _refused(error)
    return _detail(profile)
