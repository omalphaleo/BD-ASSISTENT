"""Tests for the ClockOffset model against a real, migrated PostgreSQL database.

Needed because the one-row rule, the zero default and the updated_by foreign key are enforced
by the database; these tests prove those constraints work. The table is not connected to
core.clock yet (M1 task A2), so nothing here changes how now() behaves.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import reset_offset
from app.core.models import ClockOffset, User, UserRole

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config(url: str) -> Config:
    """Build an Alembic Config that targets the given database URL instead of DATABASE_URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # A bare % would be treated as ConfigParser interpolation, so it is doubled.
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
    """Insert and return a synthetic admin user that can be recorded as the offset's editor."""
    user = User(email="admin@example.com", password_hash="not-a-real-hash", role=UserRole.ADMIN)
    session.add(user)
    session.flush()
    return user


@pytest.fixture(autouse=True)
def _reset_clock_offset() -> Iterator[None]:
    """Reset the process-wide clock offset around each test so one test cannot shift another."""
    reset_offset()
    yield
    reset_offset()


def test_table_starts_empty(session: Session) -> None:
    """The migration inserts no row: with no row the offset is treated as zero."""
    assert session.execute(select(ClockOffset)).first() is None


def test_offset_defaults_to_zero_and_singleton_to_true(session: Session) -> None:
    """A row created with no values has offset_seconds 0, singleton true and no editor."""
    row = ClockOffset()
    session.add(row)
    session.flush()

    assert isinstance(row.id, uuid.UUID)
    assert row.offset_seconds == 0
    assert row.singleton is True
    assert row.updated_by is None
    assert row.updated_at.tzinfo is not None


@pytest.mark.parametrize("seconds", [86_400, -3_600], ids=["forward", "backward"])
def test_positive_and_negative_offsets_are_accepted(session: Session, seconds: int) -> None:
    """A signed offset in either direction is stored unchanged."""
    row = ClockOffset(offset_seconds=seconds)
    session.add(row)
    session.flush()
    session.expire_all()

    assert session.execute(select(ClockOffset.offset_seconds)).scalar_one() == seconds


def test_second_row_is_rejected(session: Session) -> None:
    """A second row raises IntegrityError naming the singleton unique constraint."""
    session.add(ClockOffset(offset_seconds=60))
    session.flush()
    session.add(ClockOffset(offset_seconds=120))

    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "uq_clock_offsets_singleton" in str(exc.value)


def test_singleton_false_is_rejected(session: Session) -> None:
    """singleton=false raises IntegrityError naming the CHECK, so the one-row cap holds."""
    session.add(ClockOffset(singleton=False))

    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "ck_clock_offsets_singleton" in str(exc.value)


def test_updated_by_records_the_editor(session: Session, user: User) -> None:
    """updated_by stores the editing admin's id."""
    row = ClockOffset(offset_seconds=60, updated_by=user.id)
    session.add(row)
    session.flush()

    assert row.updated_by == user.id


def test_unknown_updated_by_is_rejected_by_the_foreign_key(session: Session) -> None:
    """An updated_by that is not a user raises IntegrityError naming the foreign key."""
    session.add(ClockOffset(updated_by=uuid.uuid4()))

    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "fk_clock_offsets_updated_by_users" in str(exc.value)


def test_deleting_the_editor_keeps_the_row_and_clears_updated_by(
    session: Session, user: User
) -> None:
    """Deleting the admin who last changed the offset keeps the offset with updated_by NULL."""
    session.add(ClockOffset(offset_seconds=300, updated_by=user.id))
    session.flush()

    # Core DELETE: the database applies ON DELETE SET NULL; the ORM would not.
    session.execute(delete(User).where(User.id == user.id))
    session.expire_all()

    remaining = session.execute(select(ClockOffset)).scalar_one()
    assert (remaining.offset_seconds, remaining.updated_by) == (300, None)


def test_updated_at_is_set_on_insert(session: Session) -> None:
    """updated_at is filled from the app clock, close to real UTC when no offset is set."""
    row = ClockOffset()
    session.add(row)
    session.flush()

    assert abs((row.updated_at - datetime.now(UTC)).total_seconds()) < 5
