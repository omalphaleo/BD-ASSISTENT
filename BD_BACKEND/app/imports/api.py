"""Import routes under /imports: upload, status and worksheet selection (M2-A1).

Needed so the frontend can upload a CSV or XLSX file, see an import's state, and pick the
worksheet of a multi-sheet workbook. Thin handlers: the work is in imports.upload, the
parsers and the storage. Every route requires IMPORT_LEADS; whose imports a user may see is
decided in imports.access. Later tasks (M2-A2 to M2-A5) add mapping, progress and report
routes to this router.
"""

import logging
import uuid
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
    StorageError,
    UploadErrorKind,
    UploadRejectedError,
)
from app.imports.multipart import read_upload
from app.imports.parsers import UploadLimits, limits_from_settings
from app.imports.schemas import (
    DuplicateFileResponse,
    ImportFileResponse,
    SelectWorksheetRequest,
    UploadErrorResponse,
    UploadResponse,
)
from app.imports.storage import FileStorage, get_file_storage
from app.imports.upload import (
    DuplicateFileError,
    get_import_for_viewer,
    receive_upload,
    select_worksheet,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imports", tags=["imports"])

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
