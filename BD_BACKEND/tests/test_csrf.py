"""Tests for the CSRF token, the Origin check and CORS (M1 task A8) on a real PostgreSQL database.

Needed because these checks are the only defence besides SameSite=Lax against a foreign site
using a signed-in browser: every state-changing route must refuse a missing, wrong or foreign
token and a foreign Origin, login must stay reachable without a token, and CORS must admit
exactly the frontend. They drive the real app.main.app with plain TestClients (no automatic
token), so each test controls exactly which headers are sent.
"""

import hashlib
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.config import Settings, get_settings
from app.core import services
from app.core.csrf import CSRF_FAILED_DETAIL, CSRF_HEADER_NAME, csrf_token_for_session_token
from app.core.models import User, UserRole
from app.core.passwords import hash_password
from app.db import get_session
from app.main import app as real_app

UNUSED_DATABASE_URL = "postgresql+psycopg://user:pw@localhost:5432/unused"
# The origin the real app's CORS middleware was built with (read once, at import time).
FRONTEND_ORIGIN = get_settings().frontend_origin
FOREIGN_ORIGIN = "https://evil.example.com"
COOKIE_NAME = "bd_session"
PASSWORD = "correct-horse-battery"
# One slow Argon2 hash shared by the tests that log in.
PASSWORD_HASH = hash_password(PASSWORD)
CSRF_FAILED_BODY = {"detail": CSRF_FAILED_DETAIL}
NEW_USER = {"email": "new@example.com", "role": "rep", "password": "initial-password-123"}


@pytest.fixture
def app(db_session: Session) -> Iterator[FastAPI]:
    """The real app on the test's rolled-back session, with the frontend origin pinned."""

    def override_session() -> Iterator[Session]:
        yield db_session

    settings = Settings(
        _env_file=None,
        database_url=UNUSED_DATABASE_URL,
        session_cookie_secure=False,
        frontend_origin=FRONTEND_ORIGIN,
    )
    real_app.dependency_overrides[get_session] = override_session
    real_app.dependency_overrides[get_settings] = lambda: settings
    yield real_app
    real_app.dependency_overrides.clear()


def _make_user(session: Session, role: UserRole, label: str) -> User:
    """Insert a synthetic active user whose password is PASSWORD."""
    user = User(email=f"{label}@example.com", password_hash=PASSWORD_HASH, role=role)
    session.add(user)
    session.flush()
    return user


def _signed_in(session: Session, app: FastAPI, user: User) -> tuple[TestClient, str]:
    """Return a plain client holding a real session cookie, and that session's raw token."""
    client = TestClient(app)
    token, _ = services.create_session(session, user)
    client.cookies.set(COOKIE_NAME, token)
    return client, token


@pytest.fixture
def admin_client(app: FastAPI, db_session: Session) -> tuple[TestClient, str]:
    """A client signed in as an admin (so a passing CSRF check reaches the real handler)."""
    return _signed_in(db_session, app, _make_user(db_session, UserRole.ADMIN, "admin"))


def test_token_is_sha256_of_prefixed_session_token() -> None:
    """The token is exactly sha256("csrf:" + session token) as hex, per the A8 decision."""
    expected = hashlib.sha256(b"csrf:abc").hexdigest()

    assert csrf_token_for_session_token("abc") == expected


def test_token_differs_from_the_stored_token_hash() -> None:
    """A leaked sessions.token_hash (sha256 of the bare token) is not a valid CSRF token."""
    assert csrf_token_for_session_token("abc") != services.hash_session_token("abc")


def test_safe_methods_need_no_token(app: FastAPI, admin_client: tuple[TestClient, str]) -> None:
    """GET without a token passes for a health probe and for a signed-in read."""
    client, _ = admin_client

    assert TestClient(app).get("/health").status_code in (200, 503)
    assert client.get("/users").status_code == 200


def test_post_without_token_is_403(admin_client: tuple[TestClient, str]) -> None:
    """A signed-in POST with no X-CSRF-Token is refused with the fixed CSRF body."""
    client, _ = admin_client

    response = client.post("/users", json=NEW_USER)

    assert response.status_code == 403
    assert response.json() == CSRF_FAILED_BODY


@pytest.mark.parametrize(("method", "path"), [("post", "/users"), ("patch", "/users/x")])
def test_state_changing_routes_are_checked_before_validation(
    admin_client: tuple[TestClient, str], method: str, path: str
) -> None:
    """POST and PATCH (the only unsafe methods with routes so far) get the CSRF 403 before
    the 422 an empty body or a bad id would give. PUT and DELETE are covered by the same
    app-level dependency; they have no route to call yet."""
    client, _ = admin_client

    response = client.request(method.upper(), path, json={})

    assert response.status_code == 403
    assert response.json() == CSRF_FAILED_BODY


def test_wrong_token_is_403(admin_client: tuple[TestClient, str]) -> None:
    """A token that is not the session's token is refused."""
    client, _ = admin_client

    response = client.post("/users", json=NEW_USER, headers={CSRF_HEADER_NAME: "0" * 64})

    assert response.status_code == 403
    assert response.json() == CSRF_FAILED_BODY


def test_another_sessions_token_is_403(
    app: FastAPI, db_session: Session, admin_client: tuple[TestClient, str]
) -> None:
    """A valid token of a different session cannot be replayed on this session."""
    client, _ = admin_client
    _, other_token = _signed_in(db_session, app, _make_user(db_session, UserRole.REP, "other"))

    response = client.post(
        "/users",
        json=NEW_USER,
        headers={CSRF_HEADER_NAME: csrf_token_for_session_token(other_token)},
    )

    assert response.status_code == 403


def test_non_ascii_token_is_403_not_a_crash(admin_client: tuple[TestClient, str]) -> None:
    """A header with non-ASCII bytes is compared safely and simply fails."""
    client, _ = admin_client

    response = client.post(
        "/users", json=NEW_USER, headers=[(CSRF_HEADER_NAME.encode(), "é".encode())]
    )

    assert response.status_code == 403


def test_valid_token_reaches_the_handler(admin_client: tuple[TestClient, str]) -> None:
    """With the right token the request passes the check and the admin route runs (201)."""
    client, token = admin_client

    response = client.post(
        "/users", json=NEW_USER, headers={CSRF_HEADER_NAME: csrf_token_for_session_token(token)}
    )

    assert response.status_code == 201


def test_anonymous_post_is_403_not_401(app: FastAPI) -> None:
    """With no session cookie there is no valid token, so the CSRF 403 comes before the 401."""
    response = TestClient(app).post("/users", json=NEW_USER)

    assert response.status_code == 403
    assert response.json() == CSRF_FAILED_BODY


def test_all_csrf_failures_return_the_same_body(
    app: FastAPI, admin_client: tuple[TestClient, str]
) -> None:
    """Missing token, wrong token, foreign Origin and no cookie are indistinguishable."""
    client, token = admin_client
    good = {CSRF_HEADER_NAME: csrf_token_for_session_token(token)}
    bodies = [
        client.post("/users", json=NEW_USER).content,
        client.post("/users", json=NEW_USER, headers={CSRF_HEADER_NAME: "bad"}).content,
        client.post("/users", json=NEW_USER, headers={**good, "Origin": FOREIGN_ORIGIN}).content,
        TestClient(app).post("/users", json=NEW_USER).content,
    ]

    assert len(set(bodies)) == 1


def test_foreign_origin_is_refused_even_with_a_valid_token(
    admin_client: tuple[TestClient, str],
) -> None:
    """A present Origin that is not exactly the frontend origin gives 403."""
    client, token = admin_client
    headers = {CSRF_HEADER_NAME: csrf_token_for_session_token(token)}

    response = client.post("/users", json=NEW_USER, headers={**headers, "Origin": FOREIGN_ORIGIN})

    assert response.status_code == 403
    assert response.json() == CSRF_FAILED_BODY


@pytest.mark.parametrize(
    "origin",
    [FRONTEND_ORIGIN + "/", FRONTEND_ORIGIN.replace("http://", "https://"), "null"],
    ids=["trailing-slash", "other-scheme", "null-origin"],
)
def test_origin_must_match_exactly(admin_client: tuple[TestClient, str], origin: str) -> None:
    """Near misses (trailing slash, other scheme, the literal "null") are not the frontend."""
    client, token = admin_client
    headers = {CSRF_HEADER_NAME: csrf_token_for_session_token(token), "Origin": origin}

    assert client.post("/users", json=NEW_USER, headers=headers).status_code == 403


def test_matching_origin_with_token_passes(admin_client: tuple[TestClient, str]) -> None:
    """The frontend origin plus the right token is accepted."""
    client, token = admin_client
    headers = {CSRF_HEADER_NAME: csrf_token_for_session_token(token), "Origin": FRONTEND_ORIGIN}

    assert client.post("/users", json=NEW_USER, headers=headers).status_code == 201


def test_missing_origin_falls_through_to_the_token_check(
    admin_client: tuple[TestClient, str],
) -> None:
    """No Origin header is not a failure by itself: the token decides (both outcomes)."""
    client, token = admin_client

    assert client.post("/users", json=NEW_USER).status_code == 403
    good = {CSRF_HEADER_NAME: csrf_token_for_session_token(token)}
    assert client.post("/users", json=NEW_USER, headers=good).status_code == 201


def _login(client: TestClient, **headers: str):
    """POST /auth/login for the synthetic alice user, with extra headers."""
    body = {"email": "alice@example.com", "password": PASSWORD}
    return client.post("/auth/login", json=body, headers=headers)


def test_login_needs_no_token(app: FastAPI, db_session: Session) -> None:
    """Login is the one state-changing route exempt from the token (nobody has one yet)."""
    _make_user(db_session, UserRole.REP, "alice")

    response = _login(TestClient(app))

    assert response.status_code == 200


def test_login_with_foreign_origin_is_403_and_creates_no_session(
    app: FastAPI, db_session: Session
) -> None:
    """The Origin check still covers login, so a foreign site cannot sign a victim in."""
    _make_user(db_session, UserRole.REP, "alice")

    response = _login(TestClient(app), Origin=FOREIGN_ORIGIN)

    assert response.status_code == 403
    assert response.json() == CSRF_FAILED_BODY
    assert COOKIE_NAME not in response.cookies


def test_login_with_frontend_origin_passes(app: FastAPI, db_session: Session) -> None:
    """Login from the frontend origin is allowed."""
    _make_user(db_session, UserRole.REP, "alice")

    assert _login(TestClient(app), Origin=FRONTEND_ORIGIN).status_code == 200


def test_login_and_me_return_the_same_session_bound_token(
    app: FastAPI, db_session: Session
) -> None:
    """Login and /auth/me both return sha256("csrf:" + cookie token); a reload recovers it."""
    _make_user(db_session, UserRole.REP, "alice")
    client = TestClient(app)

    login_response = _login(client)
    cookie_token = login_response.cookies[COOKIE_NAME]
    me_response = client.get("/auth/me")

    expected = csrf_token_for_session_token(cookie_token)
    assert login_response.json()["csrf_token"] == expected
    assert me_response.json()["csrf_token"] == expected
    assert set(me_response.json()) == {"id", "email", "role", "csrf_token"}


def test_two_sessions_get_different_tokens(app: FastAPI, db_session: Session) -> None:
    """Each login makes a new session and therefore a new CSRF token."""
    _make_user(db_session, UserRole.REP, "alice")

    first = _login(TestClient(app)).json()["csrf_token"]
    second = _login(TestClient(app)).json()["csrf_token"]

    assert first != second


def test_logout_requires_a_valid_token(app: FastAPI, db_session: Session) -> None:
    """Logout is refused without or with a wrong token (session stays alive), then works."""
    _make_user(db_session, UserRole.REP, "alice")
    client = TestClient(app)
    token = _login(client).json()["csrf_token"]

    assert client.post("/auth/logout").status_code == 403
    assert client.post("/auth/logout", headers={CSRF_HEADER_NAME: "bad"}).status_code == 403
    assert client.get("/auth/me").status_code == 200
    assert client.post("/auth/logout", headers={CSRF_HEADER_NAME: token}).status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_logout_without_any_cookie_is_403(app: FastAPI) -> None:
    """No session cookie means no token can be derived, so even logout is refused."""
    assert TestClient(app).post("/auth/logout").status_code == 403


def test_rejected_requests_write_no_audit_event(
    db_session: Session, admin_client: tuple[TestClient, str]
) -> None:
    """A refused CSRF request leaves the audit log untouched (decision A8-4)."""
    client, _ = admin_client
    before = db_session.execute(select(func.count()).select_from(AuditLog)).scalar_one()

    client.post("/users", json=NEW_USER)
    client.post("/users", json=NEW_USER, headers={"Origin": FOREIGN_ORIGIN})

    after = db_session.execute(select(func.count()).select_from(AuditLog)).scalar_one()
    assert after == before


def _preflight(client: TestClient, origin: str, method: str = "POST", headers: str = "") -> object:
    """Send a CORS preflight request the way a browser would."""
    request_headers = {"Origin": origin, "Access-Control-Request-Method": method}
    if headers:
        request_headers["Access-Control-Request-Headers"] = headers
    return client.options("/users", headers=request_headers)


def test_preflight_from_the_frontend_is_allowed_with_credentials(app: FastAPI) -> None:
    """The frontend may preflight a write with X-CSRF-Token and Content-Type, with cookies."""
    response = _preflight(
        TestClient(app), FRONTEND_ORIGIN, headers=f"{CSRF_HEADER_NAME}, Content-Type"
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert CSRF_HEADER_NAME.lower() in allowed_headers


def test_preflight_from_another_origin_is_refused(app: FastAPI) -> None:
    """A foreign origin gets no allow-origin header, and the preflight itself is a 400."""
    response = _preflight(TestClient(app), FOREIGN_ORIGIN)

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_lists_no_wildcards(app: FastAPI) -> None:
    """Allowed methods and headers are explicit lists, and the origin is never "*"."""
    response = _preflight(TestClient(app), FRONTEND_ORIGIN, headers=CSRF_HEADER_NAME)

    assert response.headers["access-control-allow-origin"] != "*"
    for header in ("access-control-allow-methods", "access-control-allow-headers"):
        assert "*" not in response.headers[header]


def test_preflight_for_an_unlisted_header_is_refused(app: FastAPI) -> None:
    """A header outside the explicit list (here X-Evil) fails the preflight."""
    response = _preflight(TestClient(app), FRONTEND_ORIGIN, headers="X-Evil")

    assert response.status_code == 400


def test_csrf_403_still_carries_cors_headers(
    admin_client: tuple[TestClient, str],
) -> None:
    """The CORS layer is outermost, so the browser can read a CSRF 403 from the frontend."""
    client, _ = admin_client

    response = client.post("/users", json=NEW_USER, headers={"Origin": FRONTEND_ORIGIN})

    assert response.status_code == 403
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_openapi_documents_the_csrf_403_and_the_token_field() -> None:
    """Every state-changing operation lists a 403; reads do not; login returns csrf_token."""
    schema = real_app.openapi()

    for path_item in schema["paths"].values():
        for method, operation in path_item.items():
            if method in {"post", "put", "patch", "delete"}:
                assert "403" in operation["responses"]
    assert "403" not in schema["paths"]["/health"]["get"]["responses"]
    login_ref = schema["paths"]["/auth/login"]["post"]["responses"]["200"]["content"]
    assert login_ref["application/json"]["schema"]["$ref"].endswith("SessionUserResponse")
    assert "csrf_token" in schema["components"]["schemas"]["SessionUserResponse"]["properties"]
