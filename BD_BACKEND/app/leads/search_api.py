"""Lead search routes under /search: run a search and list the filter values (M3-A2).

Needed so the Leads screen (M3-A3), saved segments, export and NL search all query leads through
one contract. Thin handlers: the rules live in leads.search and leads.filters. Both routes need
VIEW_ALL_LEADS (every BD user, D-001, D-026) and only read data, so they write no audit event.
Search uses POST so the filter travels as the same JSON object segments store; it changes nothing.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.models import User
from app.core.permissions import Permission, require_permission
from app.db import get_session
from app.leads import search
from app.leads.search_schemas import FilterOptionsResponse, SearchRequest, SearchResponse

router = APIRouter(prefix="/search", tags=["search"])

Db = Annotated[Session, Depends(get_session)]
Viewer = Annotated[User, Depends(require_permission(Permission.VIEW_ALL_LEADS))]


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
