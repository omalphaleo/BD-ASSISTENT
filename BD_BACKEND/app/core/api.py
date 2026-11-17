"""Core routes: /health and the /auth routes (login, logout, me). Thin handlers only.

Needed so operators can tell whether the API and its database are up, and so users can sign
in and out; app.main mounts both routers. All logic lives in core.services.
"""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core import services
from app.core.cookies import clear_session_cookie, set_session_cookie
from app.core.dependencies import CurrentUser
from app.core.schemas import LoginRequest, UserResponse
from app.db import get_session

router = APIRouter()
auth_router = APIRouter(prefix="/auth", tags=["auth"])

# One message for every login failure, so the response never says which part was wrong.
INVALID_CREDENTIALS_DETAIL = "Invalid email or password"


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


@auth_router.post("/login", response_model=UserResponse)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserResponse:
    """Sign in with email and password; sets the session cookie.

    Raises:
        HTTPException: 401 with one fixed body for any credential failure; no cookie is set.
    """
    # Cookie Max-Age and the session's expires_at must agree, so one lifetime feeds both.
    lifetime = timedelta(hours=settings.session_lifetime_hours)
    # The direct peer address. Trusted-proxy handling (X-Forwarded-For) is deferred to
    # deployment; trusting that header now would let clients forge the IP in the audit log.
    ip_address = request.client.host if request.client else None
    try:
        token, user = services.login(
            db, body.email, body.password, ip_address=ip_address, lifetime=lifetime
        )
    except services.InvalidCredentialsError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_CREDENTIALS_DETAIL) from None
    set_session_cookie(response, token, settings)
    return UserResponse.model_validate(user)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
) -> Response:
    """Sign out. Needs no authentication, so an expired session can still clear its cookie."""
    services.logout(db, request.cookies.get(settings.session_cookie_name))
    # Built explicitly: a returned Response replaces the injected one, so the Set-Cookie
    # header has to be placed on this 204 itself.
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, settings)
    return response


@auth_router.get("/me", response_model=UserResponse)
def me(current_user: CurrentUser) -> UserResponse:
    """Return the signed-in user; 401 if nobody is signed in."""
    return UserResponse.model_validate(current_user)


router.include_router(auth_router)
