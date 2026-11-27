"""Import routes under /imports: upload, status and worksheet selection (M2-A1).

Needed so the frontend can upload a CSV or XLSX file, see an import's state, and pick the
worksheet of a multi-sheet workbook. Thin handlers: the work is in imports.upload, the
parsers and the storage. Every route requires IMPORT_LEADS; whose imports a user may see is
decided in imports.access. The mapping, preview and estimate routes (M2-A2) live in
imports.mapping_api and are included here; M2-A3 to M2-A5 add progress and report routes.
"""

import logging
import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.models import User
from app.core.permissions import Permission, require_permission
from app.db import get_session
from app.imports.errors import (
    ImportNotFoundError,
    StartErrorKind,
    StartRejectedError,
    StorageError,
    UploadErrorKind,
    UploadRejectedError,
)
from app.imports.mapping_api import router as mapping_router
from app.imports.multipart import read_upload
from app.imports.parsers import UploadLimits, limits_from_settings
from app.imports.pipeline import (
    ALREADY_PROCESSING_MESSAGE,
    get_progress,
    start_import,
)
from app.imports.schemas import (
    DuplicateFileResponse,
    ImportFileResponse,
    ImportProgressResponse,
    MappingErrorResponse,
    SelectWorksheetRequest,
    UploadErrorResponse,
    UploadResponse,
)
from app.imports.storage import FileStorage, get_file_storage
from app.imports.tasks import queue_import
from app.imports.upload import (
    DuplicateFileError,
    get_import_for_viewer,
    receive_upload,
    select_worksheet,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imports", tags=["imports"])
# Included first: its fixed paths (/target-fields, /profiles) must be matched before the
# "/{import_id}" routes below, which would otherwise try to read them as an import ID.
router.include_router(mapping_router)

# HTTP status for each refusal kind. 422 means "the content of the file is not usable".
UPLOAD_ERROR_STATUS: dict[UploadErrorKind, int] = {
    UploadErrorKind.UNSUPPORTED_TYPE: 415,
    UploadErrorKind.TOO_LARGE: 413,
    UploadErrorKind.TOO_MANY_ROWS: 422,
    UploadErrorKind.EMPTY_FILE: 422,
    UploadErrorKind.MALFORMED_FILE: 422,
    UploadErrorKind.UNSAFE_ARCHIVE: 422,
    UploadErrorKind.AMBIGUOUS_CSV: 422,
    UploadErrorKind.BAD_WORKSHEET: 422,
    UploadErrorKind.NOT_EDITABLE: 409,
}
NOT_FOUND_DETAIL = "Import not found"
STORAGE_FAILED_DETAIL = "The file could not be stored. Try again later."

# The upload body is read by hand (to enforce the size limit while streaming), so FastAPI
# cannot see it; this documents the multipart form for openapi.json and the generated client.
UPLOAD_REQUEST_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "allow_duplicate": {"type": "boolean", "default": False},
                    },
                }
            }
        },
    }
}

SettingsDb = Annotated[Session, Depends(get_session)]
Importer = Annotated[User, Depends(require_permission(Permission.IMPORT_LEADS))]
Storage = Annotated[FileStorage, Depends(get_file_storage)]


def get_import_queue() -> Callable[[uuid.UUID], bool]:
    """FastAPI dependency: the function that queues process_import (tests override it)."""
    return queue_import


ImportQueue = Annotated[Callable[[uuid.UUID], bool], Depends(get_import_queue)]


def _limits() -> UploadLimits:
    """Upload limits built from the current settings."""
    return limits_from_settings(get_settings())


def _rejection(error: UploadRejectedError) -> JSONResponse:
    """Turn a refusal into its 4xx response (fixed message and code, nothing from the file)."""
    body = UploadErrorResponse(detail=error.message, code=error.kind.value)
    return JSONResponse(status_code=UPLOAD_ERROR_STATUS[error.kind], content=body.model_dump())


def _client_ip(request: Request) -> str | None:
    """Client address for the audit event, if known."""
    return request.client.host if request.client else None


def _not_found() -> JSONResponse:
    """The same 404 for a missing import and for one the caller may not see."""
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": NOT_FOUND_DETAIL})


def _start_refused(error: StartRejectedError) -> JSONResponse:
    """Turn a refused start into its 409 response (fixed message and code)."""
    body = MappingErrorResponse(detail=error.message, code=error.kind.value)
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump())


def _storage_failed(error: StorageError) -> JSONResponse:
    """Generic 500 for a storage failure; the cause is logged, never returned."""
    logger.error("import file storage failed: %s", error)
    return JSONResponse(status_code=500, content={"detail": STORAGE_FAILED_DETAIL})


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=UPLOAD_REQUEST_BODY,
    responses={
        409: {"model": DuplicateFileResponse, "description": "Same file uploaded before (D-109)."},
        413: {"model": UploadErrorResponse, "description": "File larger than the limit."},
        415: {"model": UploadErrorResponse, "description": "Not a CSV or XLSX file."},
        422: {"model": UploadErrorResponse, "description": "File content not usable."},
    },
)
async def upload_import_file(
    request: Request, actor: Importer, db: SettingsDb, storage: Storage
) -> Any:
    """Upload a CSV or XLSX file (multipart: 'file' and optional 'allow_duplicate').

    A file identical to an earlier upload gets a 409 warning with the earlier date and user;
    re-upload with allow_duplicate=true to import it anyway (D-109). Nothing is stored for a
    refused upload. A multi-sheet XLSX returns its worksheets and needs
    POST /imports/{id}/worksheet before the import can continue.
    """
    limits = _limits()
    try:
        received = await read_upload(request, limits.max_bytes)
    except UploadRejectedError as error:
        return _rejection(error)
    try:
        # The parsers and the database are blocking, so they run off the event loop.
        outcome = await run_in_threadpool(
            receive_upload,
            db,
            actor,
            source=received.file,
            size_bytes=received.size_bytes,
            sha256=received.sha256,
            filename=received.filename,
            allow_duplicate=received.allow_duplicate,
            storage=storage,
            limits=limits,
            ip_address=_client_ip(request),
        )
    except DuplicateFileError as error:
        warning = DuplicateFileResponse.from_info(error.duplicate)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT, content=warning.model_dump(mode="json")
        )
    except UploadRejectedError as error:
        return _rejection(error)
    except StorageError as error:
        return _storage_failed(error)
    finally:
        await received.close()
    return UploadResponse.from_outcome(outcome.import_file, outcome.parsed)


@router.get(
    "/{import_id}",
    response_model=ImportFileResponse,
    responses={404: {"description": "No such import, or not visible to you."}},
)
def get_import_status(import_id: uuid.UUID, actor: Importer, db: SettingsDb) -> Any:
    """Return an import's state. Reps see their own imports; managers and admins see all."""
    try:
        import_file = get_import_for_viewer(db, actor, import_id)
    except ImportNotFoundError:
        return _not_found()
    return ImportFileResponse.model_validate(import_file)


@router.post(
    "/{import_id}/worksheet",
    response_model=ImportFileResponse,
    responses={
        404: {"description": "No such import, or not visible to you."},
        409: {
            "model": UploadErrorResponse,
            "description": "Not the uploader, or already past mapping.",
        },
        422: {
            "model": UploadErrorResponse,
            "description": "Unknown, empty or oversized worksheet.",
        },
    },
)
def choose_worksheet(
    import_id: uuid.UUID,
    body: SelectWorksheetRequest,
    request: Request,
    actor: Importer,
    db: SettingsDb,
    storage: Storage,
) -> Any:
    """Choose the worksheet to import from a multi-sheet XLSX (only the uploader may)."""
    try:
        import_file = select_worksheet(
            db,
            actor,
            import_id,
            body.worksheet,
            storage=storage,
            limits=_limits(),
            ip_address=_client_ip(request),
        )
    except ImportNotFoundError:
        return _not_found()
    except UploadRejectedError as error:
        return _rejection(error)
    except StorageError as error:
        return _storage_failed(error)
    return ImportFileResponse.model_validate(import_file)


@router.post(
    "/{import_id}/start",
    response_model=ImportProgressResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        404: {"description": "No such import, or not visible to you."},
        409: {
            "model": MappingErrorResponse,
            "description": "Not the uploader, wrong state, queued already or mapping incomplete.",
        },
    },
)
def start_import_processing(
    import_id: uuid.UUID,
    request: Request,
    actor: Importer,
    db: SettingsDb,
    queue: ImportQueue,
) -> Any:
    """Start processing: only the uploader, once, with a saved mapping (the wizard's last step).

    The state change is committed first, then the background job is queued with a lock on the
    import ID; a second queued job for the same import is refused with 409.
    """
    try:
        import_file = start_import(db, actor, import_id, ip_address=_client_ip(request))
    except ImportNotFoundError:
        return _not_found()
    except StartRejectedError as error:
        return _start_refused(error)
    if not queue(import_id):
        return _start_refused(
            StartRejectedError(StartErrorKind.ALREADY_PROCESSING, ALREADY_PROCESSING_MESSAGE)
        )
    return ImportProgressResponse.from_models(import_file, None)


@router.get(
    "/{import_id}/progress",
    response_model=ImportProgressResponse,
    responses={404: {"description": "No such import, or not visible to you."}},
)
def get_import_progress(import_id: uuid.UUID, actor: Importer, db: SettingsDb) -> Any:
    """Return the import's status and counters so far (same visibility as the status call)."""
    try:
        import_file, report = get_progress(db, actor, import_id)
    except ImportNotFoundError:
        return _not_found()
    return ImportProgressResponse.from_models(import_file, report)
