"""Tests for POST /auth/login, POST /auth/logout and GET /auth/me on a real PostgreSQL database.

Needed because these are the first routes that hand out credentials: they must give one
identical failure for every cause, set a correctly flagged cookie, store only token hashes,
audit every failure durably and make logout idempotent. They drive the real app.main.app.
"""

import hashlib
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from csrf_client import CsrfTestClient
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.audit.services import AuditAction
from app.config import Settings, get_settings
from app.core import services
from app.core.api import INVALID_CREDENTIALS_DETAIL
from app.core.clock import reset_offset
from app.core.csrf import csrf_token_for_session_token
from app.core.models import User, UserRole, UserSession
from app.core.passwords import hash_password, password_needs_rehash, verify_password
from app.db import get_session
from app.main import app as fastapi_app

BACKEND_DIR = Path(__file__).resolve().parent.parent
UNUSED_DATABASE_URL = "postgresql+psycopg://user:pw@localhost:5432/unused"
COOKIE_NAME = "bd_session"
PASSWORD = "correct-horse-battery"
# One Argon2 hash shared by every user in this module: hashing is deliberately slow, and
# the tests do not need a distinct hash per user.
PASSWORD_HASH = hash_password(PASSWORD)
EXPECTED_401_BODY = b'{"detail":"Invalid email or password"}'
# What the test client reports as the peer address (there is no real socket).
TEST_CLIENT_IP = "testclient"


def _alembic_config(url: str) -> Config:
    """Build an Alembic Config that targets the given database URL instead of DATABASE_URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _make_settings(**overrides: object) -> Settings:
    """Build Settings without reading .env or the environment's cookie flag.

    session_cookie_secure defaults to False here because the Docker api service sets
    SESSION_COOKIE_SECURE=false; relying on the environment would make results depend on it.
    """
    values: dict[str, object] = {"session_cookie_secure": False, **overrides}
    return Settings(_env_file=None, database_url=UNUSED_DATABASE_URL, **values)


@pytest.fixture(scope="module")
def engine(test_database_url: str) -> Iterator[Engine]:
    """Migrate the shared test database to head once per module and yield an engine for it."""
    command.upgrade(_alembic_config(test_database_url), "head")
    engine = create_engine(test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Yield a Session rolled back after each test (outer transaction plus SAVEPOINTs)."""
    with engine.connect() as connection:
        outer = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            outer.rollback()


@pytest.fixture(autouse=True)
def _reset_clock_offset() -> Iterator[None]:
    """Reset the process-wide clock offset around each test so one test cannot shift another."""
    reset_offset()
    yield
    reset_offset()


@pytest.fixture
def api_app(session: Session) -> Iterator[FastAPI]:
    """The real app with the test's database session and default test settings installed.

    Every test therefore runs with an explicit get_settings override; tests that need other
    values call use_settings() again. All overrides are removed afterwards.
    """

    def override_get_session() -> Iterator[Session]:
        """Hand the test's rolled-back session to every dependency in the request."""
        yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    default_settings = _make_settings()
    fastapi_app.dependency_overrides[get_settings] = lambda: default_settings
    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def use_settings(api_app: FastAPI) -> Callable[..., Settings]:
    """Return a function that replaces the settings override and returns the new Settings."""

    def _use(**overrides: object) -> Settings:
        """Install Settings built from the overrides for the rest of the test."""
        settings = _make_settings(**overrides)
        api_app.dependency_overrides[get_settings] = lambda: settings
        return settings

    return _use


@pytest.fixture
def client(api_app: FastAPI) -> TestClient:
    """A plain-HTTP client for the real app."""
    return CsrfTestClient(api_app)


@pytest.fixture
def make_client(api_app: FastAPI) -> Callable[..., TestClient]:
    """Return a factory for extra clients (own cookie jar), optionally over HTTPS."""

    def _make(*, https: bool = False) -> TestClient:
        """Build a client; httpx only sends Secure cookies back over https URLs."""
        base_url = "https://testserver" if https else "http://testserver"
        return CsrfTestClient(api_app, base_url=base_url)

    return _make


@pytest.fixture
def user(session: Session) -> User:
    """Insert and return the active synthetic user alice@example.com."""
    new_user = User(email="alice@example.com", password_hash=PASSWORD_HASH, role=UserRole.REP)
    session.add(new_user)
    session.flush()
    return new_user


@pytest.fixture
def disabled_user(session: Session) -> User:
    """Insert and return a disabled user (bob) who still knows the correct password."""
    new_user = User(
        email="bob@example.com", password_hash=PASSWORD_HASH, role=UserRole.REP, is_active=False
    )
    session.add(new_user)
    session.flush()
    return new_user


def _login(client: TestClient, email: str = "alice@example.com", password: str = PASSWORD):
    """POST /auth/login with the given credentials."""
    return client.post("/auth/login", json={"email": email, "password": password})


def _count_rows(session: Session, model: type) -> int:
    """Count rows of a table with a Core query, bypassing the ORM identity map."""
    return session.execute(select(func.count()).select_from(model.__table__)).scalar_one()


def _failed_login_rows(session: Session) -> list[AuditLog]:
    """Return every auth.login_failed audit row, oldest first."""
    statement = (
        select(AuditLog)
        .where(AuditLog.action == AuditAction.LOGIN_FAILED.value)
        .order_by(AuditLog.occurred_at)
    )
    return list(session.execute(statement).scalars())


def _cookie_attributes(set_cookie: str) -> list[str]:
    """Split a Set-Cookie header into its lower-cased attributes (name=value excluded)."""
    return [part.strip().lower() for part in set_cookie.split(";")[1:]]


def test_login_returns_user_without_secrets(user: User, client: TestClient) -> None:
    """Valid login: 200 and a body of exactly id, email, role and csrf_token, no hash anywhere."""
    response = _login(client)

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "email": "alice@example.com",
        "role": "rep",
        "csrf_token": csrf_token_for_session_token(response.cookies[COOKIE_NAME]),
    }
    assert "password_hash" not in response.text
    assert "argon2" not in response.text


@pytest.mark.parametrize("secure", [True, False], ids=["secure", "not-secure"])
def test_cookie_flags(
    user: User,
    session: Session,
    make_client: Callable[..., TestClient],
    use_settings: Callable[..., Settings],
    secure: bool,
) -> None:
    """Cookie: HttpOnly, Path=/, SameSite=lax, Max-Age=lifetime, no Domain; Secure per setting."""
    use_settings(session_cookie_secure=secure, session_lifetime_hours=3)
    client = make_client(https=secure)

    response = _login(client)

    attributes = _cookie_attributes(response.headers["set-cookie"])
    assert response.status_code == 200
    assert "httponly" in attributes
    assert "path=/" in attributes
    assert "samesite=lax" in attributes
    assert "max-age=10800" in attributes
    assert not any(attribute.startswith("domain") for attribute in attributes)
    assert ("secure" in attributes) is secure
    # The server-side expiry agrees with the cookie's Max-Age.
    row = session.execute(select(UserSession)).scalar_one()
    assert (row.expires_at - row.created_at).total_seconds() == 10800


def test_cookie_is_raw_token_and_only_its_hash_is_stored(
    user: User, session: Session, client: TestClient
) -> None:
    """Cookie value is the raw token; the sessions table holds only its SHA-256 hash."""
    response = _login(client)

    token = response.cookies[COOKIE_NAME]
    rows = list(session.execute(select(UserSession)).scalars())
    assert len(token) == services.TOKEN_LENGTH
    assert len(rows) == 1
    assert rows[0].token_hash == hashlib.sha256(token.encode()).hexdigest()
    for row in rows:
        stored = [str(row.id), str(row.user_id), row.token_hash, str(row.created_at)]
        assert not any(token in value for value in stored)


def test_me_after_login_returns_same_user_and_401_without_cookie(
    user: User, client: TestClient, make_client: Callable[..., TestClient]
) -> None:
    """/auth/me returns the logged-in user; a client with no cookie gets 401."""
    cookie_token = _login(client).cookies[COOKIE_NAME]

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "email": "alice@example.com",
        "role": "rep",
        "csrf_token": csrf_token_for_session_token(cookie_token),
    }
    assert make_client().get("/auth/me").status_code == 401


def test_email_is_case_and_whitespace_insensitive(user: User, client: TestClient) -> None:
    """"  ALICE@Example.com " logs in as the stored lower-case user."""
    response = _login(client, email="  ALICE@Example.com ")

    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"


def _failure_wrong_password(client: TestClient) -> object:
    """Login as the active user with a wrong password."""
    return _login(client, "alice@example.com", "wrong-password")


def _failure_unknown_email(client: TestClient) -> object:
    """Login with an email that has no user."""
    return _login(client, "nobody@example.com", PASSWORD)


def _failure_disabled_user(client: TestClient) -> object:
    """Login as the disabled user with the correct password."""
    return _login(client, "bob@example.com", PASSWORD)


FAILURE_CASES = [
    pytest.param(_failure_wrong_password, "bad_password", True, id="wrong-password"),
    pytest.param(_failure_unknown_email, "unknown_user", False, id="unknown-email"),
    pytest.param(_failure_disabled_user, "inactive_user", True, id="disabled-user"),
]


def test_all_failures_are_indistinguishable(
    user: User, disabled_user: User, client: TestClient
) -> None:
    """Wrong password, unknown email and disabled user: same status, body and headers, no cookie."""
    responses = [
        _failure_wrong_password(client),
        _failure_unknown_email(client),
        _failure_disabled_user(client),
    ]

    for response in responses:
        assert response.status_code == 401
        assert response.content == EXPECTED_401_BODY
        assert response.json() == {"detail": INVALID_CREDENTIALS_DETAIL}
        assert "set-cookie" not in response.headers
    # Full header sets are equal; no header here varies by nature (no Date or Server header
    # is added by the test transport).
    assert dict(responses[0].headers) == dict(responses[1].headers) == dict(responses[2].headers)


@pytest.mark.parametrize(("failure", "reason", "has_actor"), FAILURE_CASES)
def test_each_failure_writes_one_committed_audit_row(
    user: User,
    disabled_user: User,
    session: Session,
    client: TestClient,
    failure: Callable[[TestClient], object],
    reason: str,
    has_actor: bool,
) -> None:
    """One auth.login_failed row with the right reason, actor and IP, durable across rollback."""
    expected_user = {"bad_password": user, "inactive_user": disabled_user}.get(reason)
    failure(client)

    # The test session runs in savepoints, so "the row exists" alone proves nothing. A
    # rollback undoes everything not committed; a row that survives it was committed.
    session.rollback()
    rows = _failed_login_rows(session)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "auth.login_failed"
    assert row.object_type == "user"
    assert row.ip_address == TEST_CLIENT_IP
    assert row.summary["reason"] == reason
    if has_actor:
        assert row.actor_user_id == expected_user.id
        assert row.object_id == str(expected_user.id)
    else:
        assert row.actor_user_id is None
        assert row.object_id is None


@pytest.mark.parametrize(
    "attempted",
    ["hunter2-pasted-password", "a" * 321 + "@example.com"],
    ids=["no-at-sign", "longer-than-320"],
)
def test_email_attempted_is_omitted_for_values_that_are_not_emails(
    session: Session, attempted: str
) -> None:
    """Calling login() directly with a non-email value stores the reason but not the value."""
    with pytest.raises(services.InvalidCredentialsError):
        services.login(session, attempted, PASSWORD, ip_address=None)

    summary = _failed_login_rows(session)[0].summary
    assert summary == {"reason": "unknown_user"}


def test_audit_rows_never_contain_the_password_or_a_hash(
    user: User, session: Session, client: TestClient
) -> None:
    """After a bad-password and an unknown-email failure, no audit summary holds secrets."""
    wrong_password = "wrong-password-xyz"
    _login(client, "alice@example.com", wrong_password)
    _login(client, "nobody@example.com", wrong_password)

    summaries = [str(row.summary) for row in _failed_login_rows(session)]
    assert len(summaries) == 2
    for text in summaries:
        assert wrong_password not in text
        assert PASSWORD not in text
        assert "argon2" not in text
        assert PASSWORD_HASH not in text


@pytest.mark.parametrize(("failure", "reason", "has_actor"), FAILURE_CASES)
def test_every_login_path_runs_exactly_one_verify_password(
    user: User,
    disabled_user: User,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    failure: Callable[[TestClient], object],
    reason: str,
    has_actor: bool,
) -> None:
    """Unknown email, wrong password and disabled user each verify once; unknown uses the dummy."""
    dummy_hash = services._dummy_password_hash()  # built before counting, it is cached
    hashes_verified: list[str] = []
    real_verify = verify_password

    def counting_verify(password_hash: str, plain_password: str) -> bool:
        """Stand-in wrapper: record which hash was checked, then do the real check."""
        hashes_verified.append(password_hash)
        return real_verify(password_hash, plain_password)

    # Patched where it is used (app.core.services), not where it is defined.
    monkeypatch.setattr("app.core.services.verify_password", counting_verify)

    failure(client)

    assert len(hashes_verified) == 1
    if reason == "unknown_user":
        assert hashes_verified == [dummy_hash]
    else:
        assert hashes_verified == [PASSWORD_HASH]


def test_weak_hash_is_upgraded_on_login(session: Session, client: TestClient) -> None:
    """A hash made with weak parameters is replaced by a current one after a good login."""
    weak_hash = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    weak_user = User(email="alice@example.com", password_hash=weak_hash, role=UserRole.REP)
    session.add(weak_user)
    session.flush()
    assert password_needs_rehash(weak_hash)  # sanity: the setup really is weak

    response = _login(client)

    assert response.status_code == 200
    session.refresh(weak_user)
    assert weak_user.password_hash != weak_hash
    assert verify_password(weak_user.password_hash, PASSWORD)
    assert not password_needs_rehash(weak_user.password_hash)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"password": PASSWORD},
        {"email": "alice@example.com"},
        {"email": "alice@example.com", "password": ""},
        {"email": "alice@example.com", "password": "p" * 1025},
        {"email": "", "password": PASSWORD},
        {"email": "not-an-email", "password": PASSWORD},
        {"email": "alice@example.com", "password": PASSWORD, "remember_me": True},
    ],
    ids=[
        "empty-body",
        "missing-email",
        "missing-password",
        "empty-password",
        "password-1025-chars",
        "empty-email",
        "email-without-at",
        "extra-field",
    ],
)
def test_invalid_payload_returns_422(client: TestClient, payload: dict[str, object]) -> None:
    """Missing or invalid fields, an empty or over-long password or an extra field give 422."""
    response = client.post("/auth/login", json=payload)

    assert response.status_code == 422


def test_422_body_does_not_echo_the_password(client: TestClient) -> None:
    """A 422 caused by an over-long password must not contain that password in its body."""
    too_long_password = "secret-" + "p" * 1025

    response = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": too_long_password}
    )

    assert response.status_code == 422
    assert too_long_password not in response.text


def test_422_from_an_extra_field_does_not_echo_its_value(client: TestClient) -> None:
    """An extra field's value appears nowhere in the 422 response text."""
    extra_value = "extra-secret-value-123"

    response = client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": PASSWORD, "remember_me": extra_value},
    )

    assert response.status_code == 422
    assert extra_value not in response.text
    assert PASSWORD not in response.text


def _keys_at_any_depth(value: object) -> set[str]:
    """Collect every dict key found anywhere inside nested dicts and lists."""
    if isinstance(value, dict):
        nested = [_keys_at_any_depth(item) for item in value.values()]
        return set(value) | set().union(*nested)
    if isinstance(value, list):
        return set().union(*[_keys_at_any_depth(item) for item in value])
    return set()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"email": "alice@example.com"},
        {"email": "alice@example.com", "password": ""},
        {"email": "alice@example.com", "password": "p" * 1025},
        {"email": "alice@example.com", "password": PASSWORD, "remember_me": True},
    ],
    ids=["missing-fields", "missing-password", "empty-password", "too-long", "extra-field"],
)
def test_422_body_has_only_type_loc_and_msg(
    client: TestClient, payload: dict[str, object]
) -> None:
    """Every 422 is {"detail": [{type, loc, msg}, ...]} with no input, ctx or url key anywhere."""
    response = client.post("/auth/login", json=payload)

    body = response.json()
    assert response.status_code == 422
    assert list(body) == ["detail"]
    assert len(body["detail"]) >= 1
    for error in body["detail"]:
        assert set(error) == {"type", "loc", "msg"}
        assert error["loc"] and error["msg"]
    assert not {"input", "ctx", "url"} & _keys_at_any_depth(body)


def test_logout_revokes_the_session_and_clears_the_cookie(
    user: User, session: Session, client: TestClient
) -> None:
    """Logout: 204, cookie removed, and the old token no longer works on /auth/me."""
    token = _login(client).cookies[COOKIE_NAME]

    response = client.post("/auth/logout")

    assert response.status_code == 204
    set_cookie = response.headers["set-cookie"]
    attributes = _cookie_attributes(set_cookie)
    assert re.match(rf'^{COOKIE_NAME}=("")?;', set_cookie)
    assert "max-age=0" in attributes
    assert "path=/" in attributes
    assert "httponly" in attributes
    assert "samesite=lax" in attributes
    assert client.cookies.get(COOKIE_NAME) is None
    # Replay the old token by hand: it must be dead server-side, not merely forgotten.
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/auth/me").status_code == 401
    assert session.execute(select(UserSession)).scalar_one().revoked_at is not None


def test_logout_clears_a_secure_cookie_with_the_secure_flag(
    use_settings: Callable[..., Settings], make_client: Callable[..., TestClient]
) -> None:
    """With secure cookies on, the clearing Set-Cookie also carries Secure so browsers accept it."""
    use_settings(session_cookie_secure=True)
    client = make_client(https=True)
    # Logout needs a session cookie to derive its CSRF token from (any value will do).
    client.cookies.set(COOKIE_NAME, "garbage")

    response = client.post("/auth/logout")

    assert response.status_code == 204
    assert "secure" in _cookie_attributes(response.headers["set-cookie"])


def _garbage_cookie(client: TestClient) -> None:
    """Give the client a cookie that is not a token."""
    client.cookies.set(COOKIE_NAME, "garbage")


def _already_revoked_cookie(client: TestClient) -> None:
    """Log in and out, then present the now-revoked token again."""
    token = _login(client).cookies[COOKIE_NAME]
    client.post("/auth/logout")
    client.cookies.set(COOKIE_NAME, token)


@pytest.mark.parametrize(
    "arrange",
    [_garbage_cookie, _already_revoked_cookie],
    ids=["garbage-cookie", "already-revoked"],
)
def test_logout_is_idempotent(
    user: User, client: TestClient, arrange: Callable[[TestClient], None]
) -> None:
    """Logout with a junk or a revoked token (and its CSRF token) still gives 204 and clears.

    Logout without any cookie is 403 since A8 (no token to derive); see test_csrf.py.
    """
    arrange(client)

    response = client.post("/auth/logout")

    assert response.status_code == 204
    assert "max-age=0" in _cookie_attributes(response.headers["set-cookie"])


def test_two_logins_make_two_independent_sessions(
    user: User, session: Session, make_client: Callable[..., TestClient]
) -> None:
    """Two logins give two sessions with different tokens; logging out one keeps the other."""
    first, second = make_client(), make_client()
    first_token = _login(first).cookies[COOKIE_NAME]
    second_token = _login(second).cookies[COOKIE_NAME]

    first.post("/auth/logout")

    assert first_token != second_token
    assert _count_rows(session, UserSession) == 2
    assert first.get("/auth/me").status_code == 401
    assert second.get("/auth/me").status_code == 200


@pytest.mark.parametrize(("failure", "reason", "has_actor"), FAILURE_CASES)
def test_failed_login_creates_no_session(
    user: User,
    disabled_user: User,
    session: Session,
    client: TestClient,
    failure: Callable[[TestClient], object],
    reason: str,
    has_actor: bool,
) -> None:
    """Every kind of failed login leaves the sessions table empty."""
    failure(client)

    assert _count_rows(session, UserSession) == 0
