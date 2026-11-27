"""Lead search routes under /search: run a search and list the filter values (M3-A2).

Needed so the Leads screen (M3-A3), saved segments, export and NL search all query leads through
one contract. Thin handlers: the rules live in leads.search and leads.filters. Both routes need
VIEW_ALL_LEADS (every BD user, D-001, D-026) and only read data, so they write no audit event.
Search uses POST so the filter travels as the same JSON object segments store; it changes nothing.
The CSV export (M3-A5) needs EXPORT_CSV and writes one audit event per download.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core import clock
from app.core.models import User
from app.core.permissions import Permission, require_permission
from app.db import get_session
from app.leads import export, search
from app.leads.export import ExportTooLargeError
from app.leads.search_schemas import (
    ExportRequest,
    FilterOptionsResponse,
    SearchRequest,
    SearchResponse,
)

router = APIRouter(prefix="/search", tags=["search"])

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
# HTTP 422 as a number: the status-name constant was renamed between Starlette versions.
UNPROCESSABLE = 422

Db = Annotated[Session, Depends(get_session)]
Viewer = Annotated[User, Depends(require_permission(Permission.VIEW_ALL_LEADS))]
Exporter = Annotated[User, Depends(require_permission(Permission.EXPORT_CSV))]


@router.post("/leads", response_model=SearchResponse)
def search_leads(_viewer: Viewer, db: Db, request: SearchRequest) -> SearchResponse:
    """Return one page of leads matching the filters, with the total number of matches.

    An unknown filter field, an invalid combination or an unsupported sort is rejected with 422.
    """
    return search.search_leads(
        db,
        request.filters,
        sort=request.sort,
        direction=request.direction,
        limit=request.limit,
        offset=request.offset,
    )


@router.get("/filter-options", response_model=FilterOptionsResponse)
def get_filter_options(_viewer: Viewer, db: Db) -> FilterOptionsResponse:
    """Return the values the filter checkboxes offer (capped lists name themselves if cut)."""
    return search.get_filter_options(db)


@router.post(
    "/leads/export.csv",
    response_class=Response,
    responses={
        200: {"content": {"text/csv": {}}, "description": "Every lead matching the filters."},
        422: {"description": "Invalid filters, or more leads match than one export holds."},
    },
)
def export_leads(request: Request, exporter: Exporter, db: Db, body: ExportRequest) -> Any:
    """Download every lead matching the filters as CSV (audited, D-087).

    Needs EXPORT_CSV (every BD user). An invalid filter is a 422 like search; so is a filter
    matching more than the export limit, with the count so the user can narrow it.
    """
    try:
        result = export.export_leads(
            db,
            exporter,
            body.filters,
            sort=body.sort,
            direction=body.direction,
            ip_address=request.client.host if request.client else None,
        )
    except ExportTooLargeError as error:
        return JSONResponse(
            status_code=UNPROCESSABLE,
            content={
                "detail": f"{error.total} leads match; one export holds at most {error.limit}. "
                "Narrow the filters."
            },
        )
    filename = f"leads-{clock.now().date().isoformat()}.csv"
    return Response(
        content=result.csv,
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
