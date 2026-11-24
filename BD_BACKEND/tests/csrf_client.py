"""A test client that adds the X-CSRF-Token header by itself, like the real frontend does.

Needed because every state-changing API call now requires the token (A8); tests that are
about something else (users API, logout, permissions) use this client so they do not repeat
the header on each call. Tests of the CSRF check itself use a plain TestClient instead.
"""

from typing import Any

from fastapi.testclient import TestClient

from app.core.csrf import CSRF_HEADER_NAME, STATE_CHANGING_METHODS, csrf_token_for_session_token

DEFAULT_COOKIE_NAME = "bd_session"


class CsrfTestClient(TestClient):
    """TestClient that sends the CSRF token derived from the session cookie it holds.

    Does nothing when the client has no session cookie (so the missing-token path stays
    testable) or when the caller already passed the header (so a wrong token can be sent).
    """

    def request(self, method: str, url: Any, **kwargs: Any) -> Any:
        """Add X-CSRF-Token to state-changing requests, then send them as usual."""
        session_token = self.cookies.get(DEFAULT_COOKIE_NAME)
        headers = dict(kwargs.pop("headers", None) or {})
        if (
            method.upper() in STATE_CHANGING_METHODS
            and session_token
            and CSRF_HEADER_NAME not in headers
        ):
            headers[CSRF_HEADER_NAME] = csrf_token_for_session_token(session_token)
        return super().request(method, url, headers=headers or None, **kwargs)
