"""FastAPI dependencies that turn the session cookie into the signed-in user.

Needed so every protected route declares one thin dependency (CurrentUser) instead of
parsing cookies itself; login/logout and the permission checks build on it.
This is authentication only ("who are you?"): it raises 401, never 403.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.models import User
from app.core.services import AuthenticatedSession, get_active_session
from app.db import get_session

# One message for every failure, so a response never reveals whether a token was once valid.
NOT_AUTHENTICATED_DETAIL = "Not authenticated"


def get_current_session(
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedSession:
    """Resolve the session cookie to an active session and its user.

    Read-only: sets no cookie, extends nothing and writes nothing. The token is never
    logged.

    Raises:
        HTTPException: 401 if the cookie is missing or empty, or the token is unknown,
            expired, revoked or belongs to a disabled user (all with the same body).
    """
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, NOT_AUTHENTICATED_DETAIL)

    authenticated = get_active_session(db, token)
    if authenticated is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, NOT_AUTHENTICATED_DETAIL)
    return authenticated


def get_current_user(
    auth: Annotated[AuthenticatedSession, Depends(get_current_session)],
) -> User:
    """Return the signed-in user of the current request.

    Raises:
        HTTPException: 401 via get_current_session when nobody is signed in.
    """
    return auth.user


# Routes annotate a parameter with this type to require a signed-in user.
CurrentUser = Annotated[User, Depends(get_current_user)]
