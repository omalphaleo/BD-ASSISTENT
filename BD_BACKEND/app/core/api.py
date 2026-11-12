"""Core routes. Thin handlers only."""

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
        return JSONResponse(
            status_code=503, content={"status": "degraded", "database": "unavailable"}
        )
    return JSONResponse(content={"status": "ok", "database": "ok"})
