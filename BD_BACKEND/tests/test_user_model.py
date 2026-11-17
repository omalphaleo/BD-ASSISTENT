"""Tests for the User model against a real, migrated PostgreSQL database.

Needed because the email rules, role enum and timestamp defaults are enforced partly by
the database; these tests prove those constraints work and that models.py and the 0002
migration describe the same schema.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401  # registers every model so the drift test sees all tables
from app.core.clock import reset_offset, set_offset
from app.core.models import User, UserRole
from app.db import Base

BACKEND_DIR = Path(__file__).resolve().parent.parent
SYNTHETIC_EMAIL = "alice@example.com"
SYNTHETIC_HASH = "not-a-real-hash"


def _alembic_config(url: str) -> Config:
    """Build an Alembic Config that targets the given database URL instead of DATABASE_URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # A bare % would be treated as ConfigParser interpolation, so it is doubled.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _new_user(email: str = SYNTHETIC_EMAIL) -> User:
    """Build an unsaved synthetic rep user; only the email varies between tests."""
    return User(email=email, password_hash=SYNTHETIC_HASH, role=UserRole.REP)


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
    errors tests provoke do not poison the connection and no row ever persists between tests.
    """
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


def test_valid_user_is_saved_with_generated_fields(session: Session) -> None:
    """A valid user gets an id and timezone-aware created_at/updated_at when flushed."""
    user = _new_user()
    session.add(user)
    session.flush()

    assert user.id is not None
    assert user.created_at is not None
    assert user.updated_at is not None
    assert user.created_at.tzinfo is not None


def test_duplicate_email_is_rejected(session: Session) -> None:
    """Two users with the same email: flush raises IntegrityError naming uq_users_email_lower."""
    session.add_all([_new_user(), _new_user()])

    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "uq_users_email_lower" in str(exc.value)


def test_mixed_case_email_is_rejected(session: Session) -> None:
    """A mixed-case email violates ck_users_email_lowercase and raises IntegrityError."""
    session.add(_new_user("Alice@example.com"))

    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "ck_users_email_lowercase" in str(exc.value)


def test_unknown_role_is_rejected_by_the_database(session: Session) -> None:
    """Raw SQL inserting role 'owner' (not in user_role) is rejected with DataError."""
    now_value = datetime.now(UTC)
    # Raw SQL on purpose: it bypasses the Python enum, so only the database enum can reject it.
    insert = text(
        "INSERT INTO users (id, email, password_hash, role, is_active, created_at, updated_at) "
        "VALUES (:id, :email, :password_hash, 'owner', true, :created_at, :updated_at)"
    )

    with pytest.raises(DataError):
        session.execute(
            insert,
            {
                "id": uuid.uuid4(),
                "email": SYNTHETIC_EMAIL,
                "password_hash": SYNTHETIC_HASH,
                "created_at": now_value,
                "updated_at": now_value,
            },
        )


def test_is_active_defaults_to_true(session: Session) -> None:
    """A user created without is_active is active after flush."""
    user = _new_user()
    session.add(user)
    session.flush()

    assert user.is_active is True


def test_created_at_follows_the_clock_offset(session: Session) -> None:
    """With the clock shifted +1 day, created_at is about one day ahead of real UTC."""
    set_offset(timedelta(days=1))
    user = _new_user()
    session.add(user)
    session.flush()

    expected = datetime.now(UTC) + timedelta(days=1)
    assert abs(user.created_at - expected) < timedelta(seconds=5)


def test_models_match_the_migrated_schema(engine: Engine) -> None:
    """Alembic autogenerate finds no differences between the models and the migrated database."""
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)

    assert diff == []
