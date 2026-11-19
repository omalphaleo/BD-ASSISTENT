"""Tests for the Setting model against a real, migrated PostgreSQL database.

Needed because the key format, key uniqueness, version rule and the updated_by foreign key
are enforced by the database; these tests prove those constraints work, that JSON values of
every shape round-trip, and that created_at follows the project clock (M1 task A2).
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, delete, null, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import reset_offset, set_offset
from app.core.models import Setting, User, UserRole

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
    """Insert and return a synthetic admin user that can be recorded as a setting's editor."""
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


def test_valid_setting_is_saved_with_generated_fields(session: Session) -> None:
    """A valid setting gets an id, version 1, tz-aware timestamps and no editor."""
    setting = Setting(key="email.blocked_domains", value=["gmail.com"])
    session.add(setting)
    session.flush()

    assert isinstance(setting.id, uuid.UUID)
    assert setting.version == 1
    assert setting.created_at.tzinfo is not None
    assert setting.updated_at.tzinfo is not None
    assert setting.updated_by is None


def test_duplicate_key_is_rejected(session: Session) -> None:
    """A second setting with the same key raises IntegrityError naming the unique constraint."""
    session.add(Setting(key="sending.daily_limit", value=50))
    session.flush()
    session.add(Setting(key="sending.daily_limit", value=60))

    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "uq_settings_key" in str(exc.value)


@pytest.mark.parametrize(
    "key",
    ["Email.Blocked", "has space", "dash-key", "unicode.é", "semi;colon", ""],
    ids=["uppercase", "space", "dash", "non-ascii", "symbol", "empty"],
)
def test_invalid_key_format_is_rejected(session: Session, key: str) -> None:
    """Keys with uppercase letters, spaces, other symbols or no characters are rejected."""
    session.add(Setting(key=key, value=1))

    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "ck_settings_key_format" in str(exc.value)


@pytest.mark.parametrize(
    "key",
    ["email.blocked_domains", "clock.max_offset", "a", "limits_2.per_day"],
    ids=["dotted", "dotted-underscore", "single-letter", "digits"],
)
def test_valid_key_format_is_accepted(session: Session, key: str) -> None:
    """Lowercase letters, digits, underscores and dots are accepted in a key."""
    session.add(Setting(key=key, value=1))

    session.flush()


@pytest.mark.parametrize(
    "value",
    [["info", "sales"], 50, "gemini-model", True, {"nested": [1, 2]}],
    ids=["list", "number", "string", "boolean", "object"],
)
def test_json_value_round_trips(session: Session, value: object) -> None:
    """Lists, numbers, strings, booleans and objects come back from the database unchanged."""
    session.add(Setting(key="test.value", value=value))
    session.flush()
    session.expire_all()

    stored = session.execute(select(Setting.value).where(Setting.key == "test.value")).scalar_one()
    assert stored == value


def test_null_database_value_is_rejected(session: Session) -> None:
    """An SQL NULL in the value column raises IntegrityError (JSON null is a different thing)."""
    # A Python None would be stored as JSON null, so an explicit SQL NULL is used instead.
    stmt = Setting.__table__.insert().values(
        key="test.null",
        value=null(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    with pytest.raises(IntegrityError) as exc:
        session.execute(stmt)

    assert "null value in column" in str(exc.value)


def test_version_defaults_to_one_and_zero_is_rejected(session: Session) -> None:
    """version defaults to 1; an explicit 0 raises IntegrityError naming the CHECK."""
    default = Setting(key="test.default_version", value=1)
    session.add(default)
    session.flush()
    assert default.version == 1

    session.add(Setting(key="test.zero_version", value=1, version=0))
    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "ck_settings_version_positive" in str(exc.value)


def test_updated_by_records_the_editor(session: Session, user: User) -> None:
    """updated_by stores the editing user's id."""
    setting = Setting(key="test.editor", value=1, updated_by=user.id)
    session.add(setting)
    session.flush()

    assert setting.updated_by == user.id


def test_unknown_updated_by_is_rejected_by_the_foreign_key(session: Session) -> None:
    """An updated_by that is not a user raises IntegrityError naming the foreign key."""
    session.add(Setting(key="test.bad_editor", value=1, updated_by=uuid.uuid4()))

    with pytest.raises(IntegrityError) as exc:
        session.flush()

    assert "fk_settings_updated_by_users" in str(exc.value)


def test_deleting_the_editor_keeps_the_setting_and_clears_updated_by(
    session: Session, user: User
) -> None:
    """Deleting the user who last edited a setting keeps the setting with updated_by NULL."""
    setting = Setting(key="test.survives", value=1, updated_by=user.id)
    session.add(setting)
    session.flush()

    # Core DELETE: the database applies ON DELETE SET NULL; the ORM would not.
    session.execute(delete(User).where(User.id == user.id))
    session.expire_all()

    remaining = session.execute(select(Setting).where(Setting.key == "test.survives")).scalar_one()
    assert remaining.updated_by is None


def test_created_at_follows_the_clock_offset(session: Session) -> None:
    """With the clock shifted +1 day, created_at is about one day ahead of real UTC."""
    set_offset(timedelta(days=1))
    setting = Setting(key="test.clock", value=1)
    session.add(setting)
    session.flush()

    expected = datetime.now(UTC) + timedelta(days=1)
    assert abs(setting.created_at - expected) < timedelta(seconds=5)
