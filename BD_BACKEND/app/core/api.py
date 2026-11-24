"""Core routes: /health, the /auth routes (login, logout, me) and the /users routes. Thin handlers.

Needed so operators can tell whether the API and its database are up, users can sign in and
out, and admins can manage users; app.main mounts the combined router. All logic lives in
core.services and core.user_services. Every route declares its access here: public_route, or
require_permission (core.permissions).
"""

from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core import services, user_services
from app.core.cookies import clear_session_cookie, set_session_cookie
from app.core.csrf import csrf_token_for_session_token
from app.core.models import User
from app.core.permissions import Permission, public_route, require_permission
from app.core.schemas import (
    ChangeRoleRequest,
    CreateUserRequest,
    LoginRequest,
    SessionUserResponse,
    UserDetailResponse,
    UserResponse,
)
from app.db import get_session

router = APIRouter()
auth_router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])

# One message for every login failure, so the response never says which part was wrong.
INVALID_CREDENTIALS_DETAIL = "Invalid email or password"

# Fixed client-facing messages for expected user-management failures (status, detail).
USER_ERROR_RESPONSES: dict[type[user_services.UserManagementError], tuple[int, str]] = {
    user_services.UserNotFoundError: (status.HTTP_404_NOT_FOUND, "User not found"),
    user_services.EmailAlreadyExistsError: (status.HTTP_409_CONFLICT, "Email already registered"),
    user_services.SelfModificationError: (
        status.HTTP_409_CONFLICT,
        "You cannot deactivate or change the role of your own account",
    ),
    user_services.LastAdminError: (
        status.HTTP_409_CONFLICT,
        "The last active admin cannot be deactivated or demoted",
    ),
}


def _http_error(error: user_services.UserManagementError) -> HTTPException:
    """Translate an expected user-management failure into its fixed HTTP error."""
    status_code, detail = USER_ERROR_RESPONSES[type(error)]
    return HTTPException(status_code, detail)


@router.get("/health", tags=["core"], dependencies=[Depends(public_route)])
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


@auth_router.post(
    "/login", response_model=SessionUserResponse, dependencies=[Depends(public_route)]
)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionUserResponse:
    """Sign in with email and password; sets the session cookie and returns the CSRF token.

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
    return SessionUserResponse(
        **UserResponse.model_validate(user).model_dump(),
        csrf_token=csrf_token_for_session_token(token),
    )


@auth_router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(public_route)]
)
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


@auth_router.get("/me", response_model=SessionUserResponse)
def me(
    current_user: Annotated[User, Depends(require_permission(Permission.VIEW_OWN_PROFILE))],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionUserResponse:
    """Return the signed-in user and the session's CSRF token (the frontend calls this after
    a page reload to get the token back); 401 if nobody is signed in."""
    # The guard above only passes with a valid session cookie, so the cookie is present here.
    session_token = request.cookies[settings.session_cookie_name]
    return SessionUserResponse(
        **UserResponse.model_validate(current_user).model_dump(),
        csrf_token=csrf_token_for_session_token(session_token),
    )


def _client_ip(request: Request) -> str | None:
    """Return the direct peer address for the audit log (same rule as login)."""
    return request.client.host if request.client else None


@users_router.get("/me", response_model=UserDetailResponse)
def my_profile(
    current_user: Annotated[User, Depends(require_permission(Permission.VIEW_OWN_PROFILE))],
) -> UserDetailResponse:
    """Return the signed-in user's own profile (every role may view itself)."""
    return UserDetailResponse.model_validate(current_user)


@users_router.get("", response_model=list[UserDetailResponse])
def list_users(
    actor: Annotated[User, Depends(require_permission(Permission.MANAGE_USERS))],
    db: Annotated[Session, Depends(get_session)],
) -> list[UserDetailResponse]:
    """List all users, ordered by email (admin only)."""
    return [UserDetailResponse.model_validate(u) for u in user_services.list_users(db, actor)]


@users_router.post("", response_model=UserDetailResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    body: CreateUserRequest,
    request: Request,
    actor: Annotated[User, Depends(require_permission(Permission.MANAGE_USERS))],
    db: Annotated[Session, Depends(get_session)],
) -> UserDetailResponse:
    """Create a user with an initial password (admin only).

    Raises:
        HTTPException: 409 if the email is already registered.
    """
    try:
        user = user_services.create_user(
            db,
            actor,
            email=body.email,
            password=body.password,
            role=body.role,
            ip_address=_client_ip(request),
        )
    except user_services.UserManagementError as error:
        raise _http_error(error) from None
    return UserDetailResponse.model_validate(user)


@users_router.patch("/{user_id}", response_model=UserDetailResponse)
def change_user_role(
    user_id: UUID,
    body: ChangeRoleRequest,
    request: Request,
    actor: Annotated[User, Depends(require_permission(Permission.MANAGE_USERS))],
    db: Annotated[Session, Depends(get_session)],
) -> UserDetailResponse:
    """Change a user's role (admin only).

    Raises:
        HTTPException: 404 if the user does not exist; 409 if an admin safeguard applies.
    """
    try:
        user = user_services.change_role(
            db, actor, user_id, role=body.role, ip_address=_client_ip(request)
        )
    except user_services.UserManagementError as error:
        raise _http_error(error) from None
    return UserDetailResponse.model_validate(user)


@users_router.post("/{user_id}/deactivate", response_model=UserDetailResponse)
def deactivate_user(
    user_id: UUID,
    request: Request,
    actor: Annotated[User, Depends(require_permission(Permission.MANAGE_USERS))],
    db: Annotated[Session, Depends(get_session)],
) -> UserDetailResponse:
    """Deactivate a user and end all their sessions (admin only).

    Raises:
        HTTPException: 404 if the user does not exist; 409 if an admin safeguard applies.
    """
    try:
        user = user_services.deactivate_user(db, actor, user_id, ip_address=_client_ip(request))
    except user_services.UserManagementError as error:
        raise _http_error(error) from None
    return UserDetailResponse.model_validate(user)


@users_router.post("/{user_id}/reactivate", response_model=UserDetailResponse)
def reactivate_user(
    user_id: UUID,
    request: Request,
    actor: Annotated[User, Depends(require_permission(Permission.MANAGE_USERS))],
    db: Annotated[Session, Depends(get_session)],
) -> UserDetailResponse:
    """Reactivate a deactivated user (admin only); they must sign in again.

    Raises:
        HTTPException: 404 if the user does not exist.
    """
    try:
        user = user_services.reactivate_user(db, actor, user_id, ip_address=_client_ip(request))
    except user_services.UserManagementError as error:
        raise _http_error(error) from None
    return UserDetailResponse.model_validate(user)


router.include_router(auth_router)
router.include_router(users_router)
