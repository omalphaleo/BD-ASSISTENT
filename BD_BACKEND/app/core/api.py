"""Core routes (currently only /health). Thin handlers only.

Needed so Docker, load balancers and operators can tell whether the API and its database
are up; app.main mounts this router.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session

router = APIRouter()


@router.get("/health", tags=["core"])
def health(session: Session = Depends(get_session)) -> JSONResponse:
    """Liveness plus a database check. 503 when the database is unreachable."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # Report degraded status rather than a 500 so probes get a clear, stable body
        # and no internal error text or stack trace reaches the caller.
        return JSONResponse(
            status_code=503, content={"status": "degraded", "database": "unavailable"}
        )
    return JSONResponse(content={"status": "ok", "database": "ok"})
