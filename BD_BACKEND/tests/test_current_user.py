"""Tests for the current_user FastAPI dependency on a real PostgreSQL database.

Needed because every protected route will rely on get_current_session/get_current_user to
answer "who are you?" with 401 for every failure and no side effects; a tiny app built here
stands in for the login and protected routes that do not exist yet.
"""

from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, update
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core import services
from app.core.clock import reset_offset, set_offset
from app.core.dependencies import (
    NOT_AUTHENTICATED_DETAIL,
    CurrentUser,
    get_current_session,
    get_current_user,
)
from app.core.models import User, UserRole, UserSession
from app.core.services import AuthenticatedSession
from app.db import get_session

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_COOKIE = "bd_session"
EXPECTED_401 = {"detail": NOT_AUTHENTICATED_DETAIL}


def _alembic_config(url: str) -> Config:
    """Build an Alembic Config that targets the given database URL instead of DATABASE_URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


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


@pytest.fixture
def user(session: Session) -> User:
    """Insert and return the synthetic user alice@example.com."""
    new_user = User(email="alice@example.com", password_hash="not-a-real-hash", role=UserRole.REP)
    session.add(new_user)
    session.flush()
    return new_user


@pytest.fixture(autouse=True)
def _reset_clock_offset() -> Iterator[None]:
    """Reset the process-wide clock offset around each test so one test cannot shift another."""
    reset_offset()
    yield
    reset_offset()


@pytest.fixture
def app(session: Session) -> FastAPI:
    """Build a tiny app with two protected routes that uses the test's database session."""
    test_app = FastAPI()

    @test_app.get("/me")
    def me(current: CurrentUser) -> dict[str, str]:
        """Stand-in protected route; returns explicit fields, never the whole User."""
        return {"id": str(current.id), "email": current.email, "role": current.role.value}

    @test_app.get("/twice")
    def twice(
        first: Annotated[User, Depends(get_current_user)],
        second: Annotated[User, Depends(get_current_user)],
        auth: Annotated[AuthenticatedSession, Depends(get_current_session)],
    ) -> dict[str, bool]:
        """Stand-in route using the dependencies three times to prove per-request caching."""
        return {"same_user": first is second and second is auth.user}

    def override_get_session() -> Iterator[Session]:
        """Hand the test's rolled-back session to every dependency in the request."""
        yield session

    test_app.dependency_overrides[get_session] = override_get_session
    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Return a TestClient for the tiny app."""
    return TestClient(app)


def _sign_in(session: Session, user: User, client: TestClient) -> tuple[str, UserSession]:
    """Create a session for the user and store its token in the client's default cookie."""
    token, row = services.create_session(session, user)
    client.cookies.set(DEFAULT_COOKIE, token)
    return token, row


def _expire_by_clock() -> None:
    """Move the clock past the configured session lifetime."""
    set_offset(timedelta(hours=get_settings().session_lifetime_hours + 1))


def _disable(session: Session, user: User) -> None:
    """Disable the user with a Core UPDATE."""
    session.execute(update(User).where(User.id == user.id).values(is_active=False))


def test_no_cookie_returns_401(client: TestClient) -> None:
    """No cookie: 401 with exactly the shared body."""
    response = client.get("/me")

    assert response.status_code == 401
    assert response.json() == EXPECTED_401


def test_valid_cookie_returns_the_user(session: Session, user: User, client: TestClient) -> None:
    """Valid cookie: 200 with the user's id, email and role."""
    _sign_in(session, user, client)

    response = client.get("/me")

    assert response.status_code == 200
    assert response.json() == {"id": str(user.id), "email": "alice@example.com", "role": "rep"}


@pytest.mark.parametrize(
    "cookie_value",
    [services.generate_session_token(), "short", "", "x" * 10_000],
    ids=["unknown-token", "wrong-length", "empty", "10000-chars"],
)
def test_bad_cookie_values_return_401_not_500(client: TestClient, cookie_value: str) -> None:
    """Unknown, wrong-length, empty and huge cookies: 401 each, never a server error."""
    client.cookies.set(DEFAULT_COOKIE, cookie_value)

    response = client.get("/me")

    assert response.status_code == 401
    assert response.json() == EXPECTED_401


def test_expired_session_returns_401(session: Session, user: User, client: TestClient) -> None:
    """Clock moved past session_lifetime_hours after creation: 401."""
    _sign_in(session, user, client)
    _expire_by_clock()

    assert client.get("/me").status_code == 401


def test_revoked_session_returns_401(session: Session, user: User, client: TestClient) -> None:
    """Revoked session: 401."""
    token, _ = _sign_in(session, user, client)
    services.revoke_session(session, token)

    assert client.get("/me").status_code == 401


def test_disabled_user_returns_401(session: Session, user: User, client: TestClient) -> None:
    """User disabled after sign-in: 401 on the next request."""
    _sign_in(session, user, client)
    _disable(session, user)

    assert client.get("/me").status_code == 401


def _arrange_no_cookie(session: Session, user: User, client: TestClient) -> None:
    """Leave the client without any cookie."""


def _arrange_unknown(session: Session, user: User, client: TestClient) -> None:
    """Give the client a well-formed token that was never issued."""
    client.cookies.set(DEFAULT_COOKIE, services.generate_session_token())


def _arrange_expired(session: Session, user: User, client: TestClient) -> None:
    """Sign in, then move the clock past expiry."""
    _sign_in(session, user, client)
    _expire_by_clock()


def _arrange_revoked(session: Session, user: User, client: TestClient) -> None:
    """Sign in, then revoke the session."""
    token, _ = _sign_in(session, user, client)
    services.revoke_session(session, token)


def _arrange_disabled(session: Session, user: User, client: TestClient) -> None:
    """Sign in, then disable the user."""
    _sign_in(session, user, client)
    _disable(session, user)


@pytest.mark.parametrize(
    "arrange",
    [_arrange_no_cookie, _arrange_unknown, _arrange_expired, _arrange_revoked, _arrange_disabled],
    ids=["no-cookie", "unknown", "expired", "revoked", "disabled"],
)
def test_every_failure_has_an_identical_body(
    session: Session,
    user: User,
    client: TestClient,
    arrange: Callable[[Session, User, TestClient], None],
) -> None:
    """All failure causes return the same status and body, so responses reveal nothing."""
    arrange(session, user, client)

    response = client.get("/me")

    assert response.status_code == 401
    assert response.json() == EXPECTED_401
    assert response.content == b'{"detail":"Not authenticated"}'


def test_role_change_is_visible_on_next_request(
    session: Session, user: User, client: TestClient
) -> None:
    """A Core UPDATE of the role shows on the next request despite a stale identity map."""
    _sign_in(session, user, client)
    assert user.role == UserRole.REP  # loads the object so the identity map holds it
    assert client.get("/me").json()["role"] == "rep"

    # Update the plain table, not the ORM entity: an entity UPDATE would synchronize the
    # in-memory object and hide the staleness this test needs.
    users_table = User.__table__
    session.execute(
        update(users_table).where(users_table.c.id == user.id).values(role=UserRole.ADMIN)
    )
    assert user.role == UserRole.REP  # the ORM object really is stale now

    assert client.get("/me").json()["role"] == "admin"


def test_dependencies_are_cached_per_request(
    engine: Engine, session: Session, user: User, client: TestClient
) -> None:
    """Three uses of the dependencies in one request run exactly one sessions query."""
    _sign_in(session, user, client)
    captured: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        """Stand-in observer: keep SELECT statements that read the sessions table."""
        if statement.lstrip().upper().startswith("SELECT") and "FROM sessions" in statement:
            captured.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        first = client.get("/twice")
        count_after_first = len(captured)
        second = client.get("/twice")
        count_after_second = len(captured)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert first.json() == second.json() == {"same_user": True}
    assert count_after_first == 1
    assert count_after_second == 2


def test_cookie_name_comes_from_settings(
    app: FastAPI, session: Session, user: User, client: TestClient
) -> None:
    """With session_cookie_name=custom_sid, that cookie works and the default one does not."""
    # env files disabled so no real .env is read; the values are synthetic.
    custom = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:pw@localhost:5432/unused",
        session_cookie_name="custom_sid",
    )
    app.dependency_overrides[get_settings] = lambda: custom
    token, _ = services.create_session(session, user)

    client.cookies.set(DEFAULT_COOKIE, token)
    assert client.get("/me").status_code == 401

    client.cookies.clear()
    client.cookies.set("custom_sid", token)
    assert client.get("/me").status_code == 200


def test_request_has_no_side_effects(session: Session, user: User, client: TestClient) -> None:
    """A successful request sets no cookie and leaves expires_at and revoked_at unchanged."""
    _, row = _sign_in(session, user, client)
    expires_before, revoked_before = row.expires_at, row.revoked_at

    response = client.get("/me")

    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    session.refresh(row)
    assert row.expires_at == expires_before
    assert row.revoked_at == revoked_before
