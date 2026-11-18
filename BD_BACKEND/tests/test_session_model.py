"""Tests for the UserSession model against a real, migrated PostgreSQL database.

Needed because token uniqueness, the user foreign key (with cascade) and the expiry and
hash-length rules are enforced by the database; these tests prove those constraints work
and that created_at follows the project clock.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import reset_offset, set_offset
from app.core.models import User, UserRole, UserSession

BACKEND_DIR = Path(__file__).resolve().parent.parent
TOKEN_HASH = "a" * 64  # fake 64-character digest; real hashing is a later task


def _alembic_config(url: str) -> Config:
    """Build an Alembic Config that targets the given database URL instead of DATABASE_URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # A bare % would be treated as ConfigParser interpolation, so it is doubled.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _new_session(
    user_id: uuid.UUID,
    token_hash: str = TOKEN_HASH,
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> UserSession:
    """Build an unsaved session; defaults to a valid one expiring an hour after creation."""
    created = created_at or datetime.now(UTC)
    return UserSession(
        user_id=user_id,
        token_hash=token_hash,
        created_at=created,
        expires_at=expires_at or created + timedelta(hours=1),
    )


def _count_sessions(session: Session, user_id: uuid.UUID) -> int:
    """Count the user's sessions with a Core query, bypassing the ORM identity map."""
    table = UserSession.__table__
    stmt = select(func.count()).select_from(table).where(table.c.user_id == user_id)
    return session.execute(stmt).scalar_one()


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

    The session runs inside an outer transaction and uses SAVEPOINTs, so the constraint
    errors tests provoke do not poison the connection and no row persists between tests.
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
    """Insert and return a synthetic user (alice@example.com) that sessions belong to."""
    user = User(email="alice@example.com", password_hash="not-a-real-hash", role=UserRole.REP)
    session.add(user)
    session.flush()
    return user


@pytest.fixture(autouse=True)
def _reset_clock_offset() -> Iterator[None]:
    """Reset the process-wide clock offset around each test so one test cannot shift another."""
    reset_offset()
    yield
    reset_offset()


def test_valid_session_is_saved_with_generated_fields(session: Session, user: User) -> None:
    """A valid session gets an id and tz-aware created_at; revoked_at stays None."""
    new_session = UserSession(
        user_id=user.id,
        token_hash=TOKEN_HASH,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(new_session)
    session.flush()

    assert new_session.id is not None
    assert new_session.created_at.tzinfo is not None
    assert new_session.revoked_at is None


def test_duplicate_token_hash_is_rejected(session: Session, user: User) -> None:
    """Two sessions with one token_hash: IntegrityError naming uq_sessions_token_hash."""
    session.add_all([_new_session(user.id), _new_session(user.id)])

    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "uq_sessions_token_hash" in str(exc.value)


def test_unknown_user_is_rejected_by_the_foreign_key(session: Session) -> None:
    """A session for a user_id that does not exist raises IntegrityError naming the FK."""
    session.add(_new_session(uuid.uuid4()))

    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "fk_sessions_user_id_users" in str(exc.value)


def test_deleting_the_user_deletes_their_sessions(session: Session, user: User) -> None:
    """Deleting a user row cascades: none of the user's sessions remain."""
    session.add(_new_session(user.id))
    session.flush()
    assert _count_sessions(session, user.id) == 1

    # Core delete: the cascade happens in the database, not in the ORM.
    users = User.__table__
    session.execute(delete(users).where(users.c.id == user.id))
    session.flush()

    assert _count_sessions(session, user.id) == 0


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(seconds=-1)], ids=["equal", "earlier"])
def test_expiry_not_after_creation_is_rejected(
    session: Session, user: User, offset: timedelta
) -> None:
    """expires_at equal to or earlier than created_at raises IntegrityError naming the CHECK."""
    created = datetime.now(UTC)
    session.add(_new_session(user.id, created_at=created, expires_at=created + offset))

    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "ck_sessions_expires_after_created" in str(exc.value)


@pytest.mark.parametrize("bad_hash", ["a" * 63, ""], ids=["too-short", "empty"])
def test_token_hash_must_be_64_characters(session: Session, user: User, bad_hash: str) -> None:
    """A token_hash that is not 64 characters raises IntegrityError naming the length CHECK."""
    session.add(_new_session(user.id, token_hash=bad_hash))

    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "ck_sessions_token_hash_length" in str(exc.value)


def test_created_at_follows_the_clock_offset(session: Session, user: User) -> None:
    """With the clock shifted +1 day, created_at is about one day ahead of real UTC."""
    set_offset(timedelta(days=1))
    new_session = UserSession(
        user_id=user.id,
        token_hash=TOKEN_HASH,
        expires_at=datetime.now(UTC) + timedelta(days=3),
    )
    session.add(new_session)
    session.flush()

    expected = datetime.now(UTC) + timedelta(days=1)
    assert abs(new_session.created_at - expected) < timedelta(seconds=5)


def test_one_user_can_have_several_sessions(session: Session, user: User) -> None:
    """Three sessions with distinct hashes for one user are all saved."""
    session.add_all([_new_session(user.id, token_hash=c * 64) for c in "abc"])
    session.flush()

    assert _count_sessions(session, user.id) == 3
