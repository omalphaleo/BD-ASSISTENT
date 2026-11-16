"""Tests for the session service (create, look up, revoke) on a real PostgreSQL database.

Needed because session security rests on token hashing, absolute expiry, revocation and the
active-user check, and these must hold against the real schema; the future login, logout and
current_user code depend on these functions behaving exactly as proven here.
"""

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.clock import reset_offset, set_offset
from app.core.models import User, UserRole, UserSession
from app.core.services import (
    TOKEN_LENGTH,
    InactiveUserError,
    create_session,
    generate_session_token,
    get_active_session,
    hash_session_token,
    revoke_all_user_sessions,
    revoke_session,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
TOLERANCE = timedelta(seconds=5)


def _alembic_config(url: str) -> Config:
    """Build an Alembic Config that targets the given database URL instead of DATABASE_URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # A bare % would be treated as ConfigParser interpolation, so it is doubled.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _count_sessions(db: Session, user_id: uuid.UUID | None = None) -> int:
    """Count sessions (optionally one user's) with Core, bypassing the ORM identity map."""
    table = UserSession.__table__
    stmt = select(func.count()).select_from(table)
    if user_id is not None:
        stmt = stmt.where(table.c.user_id == user_id)
    return db.execute(stmt).scalar_one()


def _make_user(db: Session, email: str) -> User:
    """Insert and return a synthetic active rep user."""
    new_user = User(email=email, password_hash="not-a-real-hash", role=UserRole.REP)
    db.add(new_user)
    db.flush()
    return new_user


@pytest.fixture(scope="module")
def engine(test_database_url: str) -> Iterator[Engine]:
    """Migrate the shared test database to head once per module and yield an engine for it."""
    command.upgrade(_alembic_config(test_database_url), "head")
    engine = create_engine(test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Yield a Session whose work is rolled back after each test.

    It runs inside an outer transaction and uses SAVEPOINTs, so the service's commit() only
    releases a savepoint and the outer rollback still removes every row the test created.
    """
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
    return _make_user(session, "alice@example.com")


@pytest.fixture
def bob(session: Session) -> User:
    """Insert and return the synthetic user bob@example.com."""
    return _make_user(session, "bob@example.com")


@pytest.fixture(autouse=True)
def _reset_clock_offset() -> Iterator[None]:
    """Reset the process-wide clock offset around each test so one test cannot shift another."""
    reset_offset()
    yield
    reset_offset()


def _collect_statements(session: Session) -> tuple[list[str], object]:
    """Attach a listener recording every SQL statement; return (list, listener to remove)."""
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        """Stand-in observer: remember each statement text the connection executes."""
        statements.append(statement)

    event.listen(session.connection(), "before_cursor_execute", record)
    return statements, record


def test_generated_tokens_are_43_url_safe_chars_and_differ() -> None:
    """Tokens are 43 URL-safe characters and two calls return different values."""
    first, second = generate_session_token(), generate_session_token()

    assert len(first) == TOKEN_LENGTH == 43
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", first)
    assert first != second


def test_hash_is_64_hex_chars_deterministic_and_not_the_token() -> None:
    """hash_session_token gives 64 hex chars, the same value twice, never the token itself."""
    token = generate_session_token()
    digest = hash_session_token(token)

    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert hash_session_token(token) == digest
    assert digest != token


def test_create_session_stores_only_the_hash(session: Session, user: User) -> None:
    """The stored hash matches the returned token and the raw token is in no column."""
    token, row = create_session(session, user)

    assert row.token_hash == hash_session_token(token)
    for column in UserSession.__table__.columns:
        assert token not in str(getattr(row, column.key))


def test_create_session_expires_after_the_configured_lifetime(
    session: Session, user: User
) -> None:
    """expires_at is the configured lifetime (12 hours by default) after created_at."""
    _, row = create_session(session, user)

    expected = timedelta(hours=get_settings().session_lifetime_hours)
    assert abs((row.expires_at - row.created_at) - expected) < TOLERANCE


def test_create_session_created_at_follows_the_clock_offset(
    session: Session, user: User
) -> None:
    """With the clock shifted +1 day, created_at is about one day ahead of real UTC."""
    set_offset(timedelta(days=1))
    _, row = create_session(session, user)

    assert abs(row.created_at - (datetime.now(UTC) + timedelta(days=1))) < TOLERANCE


def test_create_session_uses_a_custom_lifetime(session: Session, user: User) -> None:
    """A lifetime argument overrides the configured default."""
    _, row = create_session(session, user, lifetime=timedelta(minutes=30))

    assert row.expires_at - row.created_at == timedelta(minutes=30)


def test_create_session_rejects_an_inactive_user(session: Session, user: User) -> None:
    """An inactive user raises InactiveUserError and no session row is created."""
    user.is_active = False

    with pytest.raises(InactiveUserError):
        create_session(session, user)

    assert _count_sessions(session) == 0


def test_valid_token_returns_the_user_and_session(session: Session, user: User) -> None:
    """A fresh token resolves to its own user and session row."""
    token, row = create_session(session, user)

    result = get_active_session(session, token)

    assert result is not None
    assert result.user.id == user.id
    assert result.session.id == row.id


def test_unknown_token_returns_none(session: Session, user: User) -> None:
    """A well-formed token that was never issued returns None."""
    create_session(session, user)

    assert get_active_session(session, generate_session_token()) is None


@pytest.mark.parametrize("bad_token", ["", "short", "x" * 10_000], ids=["empty", "short", "huge"])
def test_wrong_length_token_returns_none_without_sql(session: Session, bad_token: str) -> None:
    """Empty, too-short and oversized tokens return None and execute zero SQL statements."""
    statements, listener = _collect_statements(session)
    try:
        assert get_active_session(session, bad_token) is None
    finally:
        event.remove(session.connection(), "before_cursor_execute", listener)

    assert statements == []


def test_session_is_valid_before_expiry_and_gone_after(session: Session, user: User) -> None:
    """With the clock at +11h the session is valid; at +13h (past 12h) it returns None."""
    token, _ = create_session(session, user)

    set_offset(timedelta(hours=11))
    assert get_active_session(session, token) is not None

    set_offset(timedelta(hours=13))
    assert get_active_session(session, token) is None


def test_revoked_session_returns_none(session: Session, user: User) -> None:
    """After revoke_session, the token no longer resolves."""
    token, _ = create_session(session, user)
    revoke_session(session, token)

    assert get_active_session(session, token) is None


def test_disabling_the_user_ends_the_session(session: Session, user: User) -> None:
    """Once the user is inactive, the token no longer resolves."""
    token, _ = create_session(session, user)
    user.is_active = False
    session.flush()

    assert get_active_session(session, token) is None


def test_lookup_issues_one_select_with_a_join(session: Session, user: User) -> None:
    """A lookup runs exactly one SELECT statement and it joins sessions to users."""
    token, _ = create_session(session, user)

    statements, listener = _collect_statements(session)
    try:
        assert get_active_session(session, token) is not None
    finally:
        event.remove(session.connection(), "before_cursor_execute", listener)

    # SAVEPOINT/RELEASE statements come from the test fixture, not from the service.
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1
    assert "JOIN" in selects[0].upper()


def test_role_change_is_visible_on_the_next_lookup(session: Session, user: User) -> None:
    """A role changed with a Core UPDATE shows up on the next lookup in the same Session."""
    token, _ = create_session(session, user)
    first = get_active_session(session, token)
    assert first is not None
    assert first.user.role == UserRole.REP

    # Core UPDATE (not the ORM attribute): the loaded User object is not touched.
    users = User.__table__
    session.execute(update(users).where(users.c.id == user.id).values(role=UserRole.ADMIN))

    second = get_active_session(session, token)
    assert second is not None
    assert second.user.role == UserRole.ADMIN


def test_revoke_session_is_idempotent_and_keeps_first_timestamp(
    session: Session, user: User
) -> None:
    """First revoke returns True, the second False, and revoked_at keeps its first value."""
    token, row = create_session(session, user)

    assert revoke_session(session, token) is True
    session.refresh(row)
    first_revoked_at = row.revoked_at
    assert first_revoked_at is not None

    set_offset(timedelta(hours=1))
    assert revoke_session(session, token) is False
    session.refresh(row)
    assert row.revoked_at == first_revoked_at


def test_revoke_session_returns_false_for_unknown_and_wrong_length_tokens(
    session: Session, user: User
) -> None:
    """An unissued token and a wrong-length token both return False."""
    create_session(session, user)

    assert revoke_session(session, generate_session_token()) is False
    assert revoke_session(session, "short") is False


def test_revoke_all_user_sessions_only_touches_that_users_active_sessions(
    session: Session, user: User, bob: User
) -> None:
    """Alice's two active sessions are revoked; her revoked one keeps its time; bob's is kept."""
    first_token, first_row = create_session(session, user)
    _, second_row = create_session(session, user)
    _, third_row = create_session(session, user)
    bob_token, bob_row = create_session(session, bob)

    assert revoke_session(session, first_token) is True
    session.refresh(first_row)
    first_revoked_at = first_row.revoked_at

    set_offset(timedelta(hours=1))
    assert revoke_all_user_sessions(session, user.id) == 2

    for row in (first_row, second_row, third_row, bob_row):
        session.refresh(row)
    assert first_row.revoked_at == first_revoked_at  # not re-stamped
    assert second_row.revoked_at is not None
    assert third_row.revoked_at is not None
    assert bob_row.revoked_at is None
    assert get_active_session(session, bob_token) is not None
    assert revoke_all_user_sessions(session, user.id) == 0
