"""Helpers that set and clear the session cookie on a response.

Needed so the cookie flags (HttpOnly, Secure, SameSite, Path, Max-Age) are defined in one
place; the login and logout routes call these and never build Set-Cookie headers themselves.
"""

from fastapi import Response

from app.config import Settings

# Lax: the cookie is not sent on cross-site POSTs, a first layer of CSRF defence.
SESSION_COOKIE_SAMESITE = "lax"
SESSION_COOKIE_PATH = "/"
SECONDS_PER_HOUR = 3600


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """Attach the session cookie carrying the raw token to the response.

    No Domain attribute is set, so the cookie is host-only. Max-Age equals the configured
    session lifetime so the browser drops the cookie when the server-side session expires.
    """
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_lifetime_hours * SECONDS_PER_HOUR,
        path=SESSION_COOKIE_PATH,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite=SESSION_COOKIE_SAMESITE,
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    """Make the browser delete the session cookie.

    Name, path, secure, httponly and samesite match set_session_cookie(); a mismatch in
    path or domain would make the browser keep the old cookie.
    """
    response.delete_cookie(
        key=settings.session_cookie_name,
        path=SESSION_COOKIE_PATH,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite=SESSION_COOKIE_SAMESITE,
    )
