"""CSRF protection: the session-bound token, the Origin check and the request guard.

Needed because the session is a cookie the browser attaches on its own; without a second
secret that only our frontend knows, a foreign site could trigger state-changing requests.
app.main installs verify_csrf on every route, and the login and /auth/me responses hand
the token to the frontend (M1 task A8; contract in milestone/m1.md section 16).
"""

import hashlib
import hmac
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, status

from app.config import Settings, get_settings
from app.core.schemas import ErrorResponse

CSRF_HEADER_NAME = "X-CSRF-Token"
# Domain separation: the token is a hash of the session token, but must never equal the
# stored token_hash (sha256 of the bare token), so a leaked database row is not a CSRF token.
CSRF_TOKEN_PREFIX = "csrf:"
# Methods that change state and so need the Origin and token checks. GET, HEAD and OPTIONS
# never do (CORS already governs who may read the responses).
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# The only route without a session yet, so it cannot carry a token. It still gets the
# Origin check, which stops a foreign site from signing a victim in to an attacker's account.
LOGIN_PATH = "/auth/login"
# One fixed body for every CSRF failure, so a response never says which check failed.
CSRF_FAILED_DETAIL = "CSRF check failed"


def csrf_token_for_session_token(session_token: str) -> str:
    """Return the CSRF token for a raw session token: sha256("csrf:" + token) as hex.

    Derived, not stored, so no table or column is needed and the token dies with the session.
    """
    return hashlib.sha256(f"{CSRF_TOKEN_PREFIX}{session_token}".encode()).hexdigest()


def _tokens_match(presented: str, expected: str) -> bool:
    """Compare two tokens in constant time (bytes, because compare_digest rejects non-ASCII str)."""
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def verify_csrf(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    """Reject a state-changing request that fails the Origin or CSRF-token check.

    Runs before the route's own guards, so a forged request gets 403 even when nobody is
    signed in. Safe methods pass untouched. Nothing is audited (decision A8-4).

    Raises:
        HTTPException: 403 with the fixed CSRF body if an Origin header is present and is not
            exactly the frontend origin, or (except for login) if the X-CSRF-Token header is
            missing or does not match the token derived from the session cookie. A request
            with no session cookie therefore has no valid token and is refused too.
    """
    if request.method not in STATE_CHANGING_METHODS:
        return

    # A browser always sends Origin on cross-site writes. A missing header (scripts, tests,
    # some same-origin requests) is not a failure by itself: the token check below decides.
    origin = request.headers.get("origin")
    if origin is not None and origin != settings.frontend_origin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, CSRF_FAILED_DETAIL)

    if request.url.path == LOGIN_PATH:
        return

    session_token = request.cookies.get(settings.session_cookie_name)
    presented = request.headers.get(CSRF_HEADER_NAME)
    if not session_token or not presented:
        raise HTTPException(status.HTTP_403_FORBIDDEN, CSRF_FAILED_DETAIL)
    if not _tokens_match(presented, csrf_token_for_session_token(session_token)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, CSRF_FAILED_DETAIL)


def install_csrf_openapi(app: FastAPI) -> None:
    """Document the CSRF 403 on every state-changing operation and the CSRF header.

    Wraps app.openapi, so call it after install_permission_openapi (which adds the 403 of
    guarded routes; this only extends its description) and after the routers are mounted.
    """
    build_previous_schema = app.openapi

    def openapi_with_csrf() -> dict[str, Any]:
        schema = build_previous_schema()
        error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
        schema.setdefault("components", {}).setdefault("schemas", {}).setdefault(
            "ErrorResponse", ErrorResponse.model_json_schema()
        )
        for path_item in schema["paths"].values():
            for method, operation in path_item.items():
                if method.upper() not in STATE_CHANGING_METHODS:
                    continue
                responses = operation["responses"]
                if "403" in responses:
                    # FastAPI caches the schema, so this runs again on the same dict.
                    if CSRF_FAILED_DETAIL not in responses["403"]["description"]:
                        responses["403"]["description"] += f"; or {CSRF_FAILED_DETAIL}"
                else:
                    responses["403"] = {
                        "description": CSRF_FAILED_DETAIL,
                        "content": {"application/json": {"schema": error_ref}},
                    }
        return schema

    app.openapi = openapi_with_csrf  # type: ignore[method-assign]
