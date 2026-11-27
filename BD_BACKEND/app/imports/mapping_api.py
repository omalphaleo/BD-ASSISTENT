"""Mapping, preview and estimate routes under /imports (M2-A2).

Needed so the wizard can list the fields a column may map to, choose a source profile and
default country, read and save the column mapping, preview the first rows and see an estimate
before the import starts. Thin handlers: the work is in imports.mapping and imports.preview.
Every route requires IMPORT_LEADS (saving a mapping as a profile default needs
MANAGE_SOURCE_PROFILES, admins only, D-049); whose imports a user may see or change is decided
in imports.access. This router is included by imports.api before its "/{import_id}" routes so
that the fixed paths here are matched first.
"""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.models import User
from app.core.permissions import Permission, require_permission
from app.db import get_session
from app.imports.errors import (
    ImportNotFoundError,
    MappingErrorKind,
    MappingRejectedError,
    StorageError,
    UploadRejectedError,
)
from app.imports.mapping import (
    choose_profile,
    get_mapping_view,
    list_active_profiles,
    save_mapping,
    save_mapping_as_default,
)
from app.imports.parsers import UploadLimits, limits_from_settings
from app.imports.preview import build_estimate, build_preview
from app.imports.schemas import (
    CellWarningResponse,
    ChooseProfileRequest,
    EstimateResponse,
    ImportFileResponse,
    MappingErrorResponse,
    MappingResponse,
    PreviewResponse,
    PreviewRowResponse,
    ProfileDefaultsResponse,
    ProfileOptionResponse,
    SaveDefaultRequest,
    SaveMappingRequest,
    TargetFieldResponse,
    UnmappedColumnResponse,
    UploadErrorResponse,
)
from app.imports.storage import FileStorage, get_file_storage
from app.leads.contracts import TARGET_FIELDS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["imports"])

# HTTP status for each refusal kind. 409: the import is in the wrong state for this step;
# 422: what was sent (or stored) is not usable.
MAPPING_ERROR_STATUS: dict[MappingErrorKind, int] = {
    MappingErrorKind.NOT_EDITABLE: 409,
    MappingErrorKind.WORKSHEET_REQUIRED: 409,
    MappingErrorKind.MAPPING_NOT_SAVED: 409,
    MappingErrorKind.INVALID_PROFILE: 409,
    MappingErrorKind.UNKNOWN_PROFILE: 422,
    MappingErrorKind.INVALID_MAPPING: 422,
    MappingErrorKind.FILE_NOT_READABLE: 422,
}
NOT_FOUND_DETAIL = "Import not found"
STORAGE_FAILED_DETAIL = "The file could not be read. Try again later."
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"description": "No such import, or not visible to you."},
    409: {"model": MappingErrorResponse, "description": "The import is in the wrong state."},
    422: {"model": MappingErrorResponse, "description": "The request or the file is not usable."},
}

Db = Annotated[Session, Depends(get_session)]
Importer = Annotated[User, Depends(require_permission(Permission.IMPORT_LEADS))]
ProfileAdmin = Annotated[User, Depends(require_permission(Permission.MANAGE_SOURCE_PROFILES))]
Storage = Annotated[FileStorage, Depends(get_file_storage)]


def _limits() -> UploadLimits:
    """Upload limits built from the current settings."""
    return limits_from_settings(get_settings())


def _client_ip(request: Request) -> str | None:
    """Client address for the audit event, if known."""
    return request.client.host if request.client else None


def _not_found() -> JSONResponse:
    """The same 404 for a missing import and for one the caller may not see."""
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": NOT_FOUND_DETAIL})


def _refused(error: MappingRejectedError) -> JSONResponse:
    """Turn a refused mapping step into its 4xx response (fixed message, nothing from the file)."""
    body = MappingErrorResponse(detail=error.message, code=error.kind.value)
    return JSONResponse(status_code=MAPPING_ERROR_STATUS[error.kind], content=body.model_dump())


def _unreadable(error: UploadRejectedError) -> JSONResponse:
    """The stored file can no longer be read: 422 with the parser's fixed message."""
    body = UploadErrorResponse(detail=error.message, code=error.kind.value)
    return JSONResponse(status_code=422, content=body.model_dump())


def _storage_failed(error: StorageError) -> JSONResponse:
    """Generic 500 for a storage failure; the cause is logged, never returned."""
    logger.error("import file storage failed: %s", error)
    return JSONResponse(status_code=500, content={"detail": STORAGE_FAILED_DETAIL})


@router.get("/target-fields", response_model=list[TargetFieldResponse])
def list_target_fields(_actor: Importer) -> Any:
    """The canonical fields a column can be mapped to, for the mapping dropdowns."""
    return [
        TargetFieldResponse(
            key=f.key,
            group=f.group.value,
            value_type=f.value_type.value,
            label=f.label,
            required=f.required,
        )
        for f in TARGET_FIELDS
    ]


@router.get("/profiles", response_model=list[ProfileOptionResponse])
def list_profile_options(_actor: Importer, db: Db) -> Any:
    """Active source profiles an uploader may choose for an import."""
    return [
        ProfileOptionResponse(id=p.id, name=p.name, layout=p.layout)
        for p in list_active_profiles(db)
    ]


@router.put("/{import_id}/profile", response_model=ImportFileResponse, responses=ERROR_RESPONSES)
def set_import_profile(
    import_id: uuid.UUID, body: ChooseProfileRequest, request: Request, actor: Importer, db: Db
) -> Any:
    """Choose the source profile and default country (only the uploader, before processing)."""
    try:
        import_file = choose_profile(
            db,
            actor,
            import_id,
            profile_id=body.source_profile_id,
            default_country=body.default_country,
            ip_address=_client_ip(request),
        )
    except ImportNotFoundError:
        return _not_found()
    except MappingRejectedError as error:
        return _refused(error)
    return ImportFileResponse.model_validate(import_file)


@router.get("/{import_id}/mapping", response_model=MappingResponse, responses=ERROR_RESPONSES)
def read_mapping(import_id: uuid.UUID, actor: Importer, db: Db, storage: Storage) -> Any:
    """The saved mapping, or a suggestion built from the profile and the built-in aliases.

    Profile suggestions are only suggestions: the user must confirm before one is applied.
    """
    try:
        view = get_mapping_view(db, actor, import_id, storage=storage, limits=_limits())
    except ImportNotFoundError:
        return _not_found()
    except MappingRejectedError as error:
        return _refused(error)
    except UploadRejectedError as error:
        return _unreadable(error)
    except StorageError as error:
        return _storage_failed(error)
    return MappingResponse.from_view(view)


@router.put("/{import_id}/mapping", response_model=MappingResponse, responses=ERROR_RESPONSES)
def put_mapping(
    import_id: uuid.UUID,
    body: SaveMappingRequest,
    request: Request,
    actor: Importer,
    db: Db,
    storage: Storage,
) -> Any:
    """Save the final column mapping, including fixed or reassigned headers (D-049)."""
    targets = {entry.column_index: entry.target_field for entry in body.columns}
    if len(targets) != len(body.columns):
        return _refused(
            MappingRejectedError(MappingErrorKind.INVALID_MAPPING, "A column is listed twice.")
        )
    try:
        view = save_mapping(
            db,
            actor,
            import_id,
            targets,
            storage=storage,
            limits=_limits(),
            ip_address=_client_ip(request),
        )
    except ImportNotFoundError:
        return _not_found()
    except MappingRejectedError as error:
        return _refused(error)
    except UploadRejectedError as error:
        return _unreadable(error)
    except StorageError as error:
        return _storage_failed(error)
    return MappingResponse.from_view(view)


@router.post(
    "/{import_id}/mapping/save-as-default",
    response_model=ProfileDefaultsResponse,
    responses=ERROR_RESPONSES,
)
def save_as_profile_default(
    import_id: uuid.UUID, body: SaveDefaultRequest, request: Request, actor: ProfileAdmin, db: Db
) -> Any:
    """Save the import's mapping as the defaults of a source profile (admins only)."""
    try:
        profile = save_mapping_as_default(
            db, actor, import_id, body.source_profile_id, ip_address=_client_ip(request)
        )
    except ImportNotFoundError:
        return _not_found()
    except MappingRejectedError as error:
        return _refused(error)
    columns = profile.mapping_defaults.get("columns", {})
    return ProfileDefaultsResponse(source_profile_id=profile.id, columns_in_defaults=len(columns))


@router.get("/{import_id}/preview", response_model=PreviewResponse, responses=ERROR_RESPONSES)
def read_preview(import_id: uuid.UUID, actor: Importer, db: Db, storage: Storage) -> Any:
    """The first rows of the file as the saved mapping reads them (nothing is saved)."""
    try:
        rows = build_preview(db, actor, import_id, storage=storage, limits=_limits())
    except ImportNotFoundError:
        return _not_found()
    except MappingRejectedError as error:
        return _refused(error)
    except UploadRejectedError as error:
        return _unreadable(error)
    except StorageError as error:
        return _storage_failed(error)
    return PreviewResponse(
        rows=[
            PreviewRowResponse(
                row_number=row.row_number,
                values=row.values,
                warnings=[CellWarningResponse(field=w.field, code=w.code) for w in row.warnings],
            )
            for row in rows
        ]
    )


@router.get("/{import_id}/estimate", response_model=EstimateResponse, responses=ERROR_RESPONSES)
def read_estimate(import_id: uuid.UUID, actor: Importer, db: Db, storage: Storage) -> Any:
    """What the file shows before the import starts: row counts, gaps and blocking issues."""
    try:
        estimate = build_estimate(db, actor, import_id, storage=storage, limits=_limits())
    except ImportNotFoundError:
        return _not_found()
    except MappingRejectedError as error:
        return _refused(error)
    except UploadRejectedError as error:
        return _unreadable(error)
    except StorageError as error:
        return _storage_failed(error)
    return EstimateResponse(
        rows_total=estimate.rows_total,
        rows_without_email=estimate.rows_without_email,
        rows_without_first_name=estimate.rows_without_first_name,
        warning_counts=estimate.warning_counts,
        unmapped_columns=[
            UnmappedColumnResponse(column_index=c.column_index, source_header=c.source_header)
            for c in estimate.unmapped_columns
        ],
        blocking_issues=list(estimate.blocking_issues),
        can_start=estimate.can_start,
    )
