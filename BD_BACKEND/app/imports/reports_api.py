"""Report, change-summary and download routes under /imports (M2-A5, D-050, D-111).

Needed so the frontend can show what an import did and let the importer, managers and admins
download the problem rows. Thin handlers over imports.reports and imports.downloads. The report
and change routes require IMPORT_LEADS (same as the progress route); the CSV downloads require
DOWNLOAD_IMPORT_FILES. Visibility is the object-level rule in imports.access (reps: own
imports; managers and admins: all), applied by the services. All routes answer 409 until the
import is COMPLETED or FAILED.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.models import User
from app.core.permissions import Permission, require_permission
from app.db import get_session
from app.imports.downloads import build_changes_csv, build_failed_rows_csv
from app.imports.errors import ImportNotFoundError, ReportRejectedError
from app.imports.reports import get_report, list_changes
from app.imports.schemas import (
    ChangesPageResponse,
    FailureReasonResponse,
    FieldChangeResponse,
    ImportReportResponse,
    LeadChangeResponse,
    MappingErrorResponse,
)

router = APIRouter(tags=["imports"])

NOT_FOUND_DETAIL = "Import not found"
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
# Highest page number accepted (50 leads per page covers far more than the 50,000-row limit).
MAX_PAGE = 100_000

Db = Annotated[Session, Depends(get_session)]
Importer = Annotated[User, Depends(require_permission(Permission.IMPORT_LEADS))]
Downloader = Annotated[User, Depends(require_permission(Permission.DOWNLOAD_IMPORT_FILES))]

NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    404: {"description": "No such import, or not visible to you."}
}
NOT_FINISHED_RESPONSE: dict[int | str, dict[str, Any]] = {
    409: {"model": MappingErrorResponse, "description": "The import has not finished yet."}
}


def _client_ip(request: Request) -> str | None:
    """Client address for the audit event, if known."""
    return request.client.host if request.client else None


def _not_found() -> JSONResponse:
    """The same 404 for a missing import and for one the caller may not see."""
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": NOT_FOUND_DETAIL})


def _not_finished(error: ReportRejectedError) -> JSONResponse:
    """Turn "not finished yet" into its 409 response (fixed message and code)."""
    body = MappingErrorResponse(detail=error.message, code=error.kind.value)
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump())


def _csv_response(text: str, name: str, import_id: uuid.UUID) -> Response:
    """A CSV attachment; the file name carries the import ID only, never lead data."""
    return Response(
        content=text,
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="import-{import_id}-{name}.csv"'},
    )


@router.get(
    "/{import_id}/report",
    response_model=ImportReportResponse,
    responses={**NOT_FOUND_RESPONSE, **NOT_FINISHED_RESPONSE},
)
def get_import_report(import_id: uuid.UUID, actor: Importer, db: Db) -> Any:
    """Return the totals, reason-coded failures and changed-lead count of a finished import."""
    try:
        view = get_report(db, actor, import_id)
    except ImportNotFoundError:
        return _not_found()
    except ReportRejectedError as error:
        return _not_finished(error)
    report = view.report
    return ImportReportResponse(
        status=view.import_file.status,
        filename=view.import_file.filename,
        row_count=view.import_file.row_count,
        received=report.received,
        imported=report.imported,
        updated=report.updated,
        unchanged=report.unchanged,
        duplicates_found=report.duplicates_found,
        quarantined=report.quarantined,
        rejected=report.rejected,
        failure_reasons=[
            FailureReasonResponse(code=reason.code, count=reason.count)
            for reason in view.failure_reasons
        ],
        changes_total=view.changes_total,
    )


@router.get(
    "/{import_id}/changes",
    response_model=ChangesPageResponse,
    responses={**NOT_FOUND_RESPONSE, **NOT_FINISHED_RESPONSE},
)
def get_import_changes(
    import_id: uuid.UUID,
    actor: Importer,
    db: Db,
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
) -> Any:
    """Return one page of "what changed in this import": each updated lead's old and new values."""
    try:
        result = list_changes(db, actor, import_id, page)
    except ImportNotFoundError:
        return _not_found()
    except ReportRejectedError as error:
        return _not_finished(error)
    return ChangesPageResponse(
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        items=[
            LeadChangeResponse(
                person_id=item.person_id,
                name=item.name,
                email=item.email,
                changes=[
                    FieldChangeResponse(field=c.field, label=c.label, old=c.old, new=c.new)
                    for c in item.changes
                ],
            )
            for item in result.items
        ],
    )


@router.get(
    "/{import_id}/download/failed-rows.csv",
    response_class=Response,
    responses={
        200: {"content": {"text/csv": {}}, "description": "Rejected and quarantined rows."},
        **NOT_FOUND_RESPONSE,
        **NOT_FINISHED_RESPONSE,
    },
)
def download_failed_rows(import_id: uuid.UUID, request: Request, actor: Downloader, db: Db) -> Any:
    """Download the rejected and quarantined rows with their reason (audited, D-111)."""
    try:
        text = build_failed_rows_csv(db, actor, import_id, ip_address=_client_ip(request))
    except ImportNotFoundError:
        return _not_found()
    except ReportRejectedError as error:
        return _not_finished(error)
    return _csv_response(text, "failed-rows", import_id)


@router.get(
    "/{import_id}/download/changes.csv",
    response_class=Response,
    responses={
        200: {"content": {"text/csv": {}}, "description": "One line per changed field."},
        **NOT_FOUND_RESPONSE,
        **NOT_FINISHED_RESPONSE,
    },
)
def download_changes(import_id: uuid.UUID, request: Request, actor: Downloader, db: Db) -> Any:
    """Download what the import changed, one line per changed field (audited, D-111)."""
    try:
        text = build_changes_csv(db, actor, import_id, ip_address=_client_ip(request))
    except ImportNotFoundError:
        return _not_found()
    except ReportRejectedError as error:
        return _not_finished(error)
    return _csv_response(text, "changes", import_id)
