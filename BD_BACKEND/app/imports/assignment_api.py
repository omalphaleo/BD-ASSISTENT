"""Owner-assignment routes under /imports (M2-A4): unmatched owners, assign, assignable users.

Needed so a manager can give the leads whose source owner matched no user to an app user
(D-075). Thin handlers over imports.assignment; every route requires ASSIGN_LEADS, and the
service re-checks that the import is visible to the caller (object-level rule).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.models import User
from app.core.permissions import Permission, require_permission
from app.db import get_session
from app.imports.assignment import (
    assign_owner_group,
    list_assignable_users,
    list_unmatched_owners,
)
from app.imports.errors import AssignErrorKind, AssignRejectedError, ImportNotFoundError
from app.imports.schemas import (
    AssignableUserResponse,
    AssignOwnerRequest,
    AssignOwnerResponse,
    MappingErrorResponse,
    UnmatchedOwnerResponse,
)

router = APIRouter(tags=["imports"])

# 409: the import is not in a state that allows it; 422: the chosen user cannot own leads.
ASSIGN_ERROR_STATUS: dict[AssignErrorKind, int] = {
    AssignErrorKind.NOT_ASSIGNABLE_YET: 409,
    AssignErrorKind.USER_NOT_ASSIGNABLE: 422,
}
NOT_FOUND_DETAIL = "Import not found"

Db = Annotated[Session, Depends(get_session)]
Assigner = Annotated[User, Depends(require_permission(Permission.ASSIGN_LEADS))]


def _client_ip(request: Request) -> str | None:
    """Client address for the audit event, if known."""
    return request.client.host if request.client else None


def _not_found() -> JSONResponse:
    """The same 404 for a missing import and for one the caller may not see."""
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": NOT_FOUND_DETAIL})


def _refused(error: AssignRejectedError) -> JSONResponse:
    """Turn a refused assignment into its 4xx response (fixed message and code)."""
    body = MappingErrorResponse(detail=error.message, code=error.kind.value)
    return JSONResponse(status_code=ASSIGN_ERROR_STATUS[error.kind], content=body.model_dump())


@router.get("/assignable-users", response_model=list[AssignableUserResponse])
def get_assignable_users(actor: Assigner, db: Db) -> Any:
    """List the active users a manager may assign leads to (id and email only)."""
    return [AssignableUserResponse(id=u.id, email=u.email) for u in list_assignable_users(db)]


@router.get(
    "/{import_id}/unmatched-owners",
    response_model=list[UnmatchedOwnerResponse],
    responses={404: {"description": "No such import, or not visible to you."}},
)
def get_unmatched_owners(import_id: uuid.UUID, actor: Assigner, db: Db) -> Any:
    """List the owner texts of an import that left leads without an owner (empty until it runs)."""
    try:
        groups = list_unmatched_owners(db, actor, import_id)
    except ImportNotFoundError:
        return _not_found()
    return [
        UnmatchedOwnerResponse(
            owner_group=g.owner_group,
            display_name=g.display_name,
            lead_count=g.lead_count,
            is_blank=not g.owner_group,
        )
        for g in groups
    ]


@router.post(
    "/{import_id}/assign-owner",
    response_model=AssignOwnerResponse,
    responses={
        404: {"description": "No such import, or not visible to you."},
        409: {"model": MappingErrorResponse, "description": "The import has not completed."},
        422: {"model": MappingErrorResponse, "description": "The user cannot own leads."},
    },
)
def post_assign_owner(
    import_id: uuid.UUID, body: AssignOwnerRequest, request: Request, actor: Assigner, db: Db
) -> Any:
    """Assign every still-unowned lead of one owner text to a user; already-owned leads stay."""
    try:
        result = assign_owner_group(
            db,
            actor,
            import_id,
            body.owner_group,
            body.user_id,
            ip_address=_client_ip(request),
        )
    except ImportNotFoundError:
        return _not_found()
    except AssignRejectedError as error:
        return _refused(error)
    return AssignOwnerResponse(assigned=result.assigned, skipped=result.skipped)
