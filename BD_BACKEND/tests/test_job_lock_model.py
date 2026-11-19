"""Tests for the JobLock model against a real, migrated PostgreSQL database.

Needed because lock-name uniqueness and the expiry rule are enforced by the database; these
tests prove those constraints work and that a lock can be taken again once released. The
acquire and release logic is not built yet (M1 task A2), so only the table is exercised.
"""

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
from app.core.models import JobLock

BACKEND_DIR = Path(__file__).resolve().parent.parent
LOCK_NAME = "poll_mailbox:00000000-0000-0000-0000-000000000001"  # synthetic mailbox id


def _alembic_config(url: str) -> Config:
    """Build an Alembic Config that targets the given database URL instead of DATABASE_URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # A bare % would be treated as ConfigParser interpolation, so it is doubled.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _new_lock(
    name: str = LOCK_NAME,
    locked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> JobLock:
    """Build an unsaved lock; defaults to a valid one expiring five minutes after it was taken."""
    taken = locked_at or datetime.now(UTC)
    return JobLock(
        name=name,
        locked_by="worker-1",
        locked_at=taken,
        expires_at=expires_at or taken + timedelta(minutes=5),
    )


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


@pytest.fixture(autouse=True)
def _reset_clock_offset() -> Iterator[None]:
    """Reset the process-wide clock offset around each test so one test cannot shift another."""
    reset_offset()
    yield
    reset_offset()


def test_valid_lock_is_saved_with_generated_fields(session: Session) -> None:
    """A valid lock gets an id and keeps its owner, name and tz-aware timestamps."""
    lock = _new_lock()
    session.add(lock)
    session.flush()

    assert lock.id is not None
    assert (lock.name, lock.locked_by) == (LOCK_NAME, "worker-1")
    assert lock.locked_at.tzinfo is not None
    assert lock.expires_at > lock.locked_at


def test_duplicate_name_is_rejected(session: Session) -> None:
    """A second lock with the same name raises IntegrityError naming the unique constraint."""
    session.add(_new_lock())
    session.flush()
    session.add(_new_lock())

    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "uq_job_locks_name" in str(exc.value)


def test_different_names_can_be_held_at_the_same_time(session: Session) -> None:
    """Locks with different names do not block each other (one per mailbox)."""
    session.add_all([_new_lock(name="poll_mailbox:a"), _new_lock(name="poll_mailbox:b")])
    session.flush()

    table = JobLock.__table__
    assert session.execute(select(func.count()).select_from(table)).scalar_one() == 2


def test_name_can_be_taken_again_after_release(session: Session) -> None:
    """After the row is deleted (released), the same name can be locked again."""
    session.add(_new_lock())
    session.flush()
    session.execute(delete(JobLock).where(JobLock.name == LOCK_NAME))

    session.add(_new_lock())
    session.flush()


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(seconds=-1)], ids=["equal", "earlier"])
def test_expiry_not_after_lock_time_is_rejected(session: Session, offset: timedelta) -> None:
    """expires_at equal to or earlier than locked_at raises IntegrityError naming the CHECK."""
    taken = datetime.now(UTC)
    session.add(_new_lock(locked_at=taken, expires_at=taken + offset))

    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "ck_job_locks_expires_after_locked" in str(exc.value)


def test_missing_owner_is_rejected(session: Session) -> None:
    """A lock without locked_by raises IntegrityError: every lock must name its holder."""
    lock = _new_lock()
    lock.locked_by = None  # type: ignore[assignment]  # deliberately invalid
    session.add(lock)

    with pytest.raises(IntegrityError):
        session.flush()


def test_locked_at_follows_the_clock_offset(session: Session) -> None:
    """With the clock shifted +1 day, locked_at defaults to about one day ahead of real UTC."""
    set_offset(timedelta(days=1))
    lock = JobLock(
        name=LOCK_NAME,
        locked_by="worker-1",
        expires_at=datetime.now(UTC) + timedelta(days=2),
    )
    session.add(lock)
    session.flush()

    expected = datetime.now(UTC) + timedelta(days=1)
    assert abs(lock.locked_at - expected) < timedelta(seconds=5)
