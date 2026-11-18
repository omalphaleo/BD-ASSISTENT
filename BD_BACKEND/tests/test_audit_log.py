"""Tests for the audit log table and record() against a real, migrated PostgreSQL database.

Needed because append-only behaviour lives in database triggers and the leaf-module rule is
an architecture constraint; these tests prove record() stores events correctly, never
commits, rejects secret keys, and that history cannot be updated, deleted or truncated.
"""

import ast
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

import app.models  # noqa: F401  # registers every model on Base.metadata
from app.audit.models import AuditLog
from app.audit.services import AuditAction, record
from app.core.clock import reset_offset, set_offset

BACKEND_DIR = Path(__file__).resolve().parent.parent
AUDIT_DIR = BACKEND_DIR / "app" / "audit"
# Modules the leaf audit package must never import.
FORBIDDEN_IMPORTS = {"app.core.models", "app.core.services", "app.core.passwords"}


def _alembic_config(url: str) -> Config:
    """Build an Alembic Config that targets the given database URL instead of DATABASE_URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # A bare % would be treated as ConfigParser interpolation, so it is doubled.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _count_rows(session: Session) -> int:
    """Count audit rows with a Core query, bypassing the ORM identity map."""
    return session.execute(select(func.count()).select_from(AuditLog.__table__)).scalar_one()


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

    The session runs inside an outer transaction and uses SAVEPOINTs, so errors tests
    provoke do not poison the connection and no row persists between tests. The outer
    rollback is also the only way to remove audit rows, since the triggers forbid DELETE.
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


def test_record_stores_all_fields(session: Session) -> None:
    """record() stores every field; occurred_at is tz-aware, summary round-trips, row is visible."""
    actor = uuid.uuid4()
    summary = {"role": {"before": "rep", "after": "manager"}, "tags": ["a", "b"]}

    entry = record(
        session,
        action=AuditAction.USER_ROLE_CHANGED,
        actor_user_id=actor,
        object_type="user",
        object_id="42",
        summary=summary,
        ip_address="2001:db8::1",
    )

    assert entry.id is not None
    assert entry.occurred_at.tzinfo is not None
    # Fresh query: proves the row is in the database, not just on the Python object.
    row = session.execute(
        select(AuditLog.__table__).where(AuditLog.__table__.c.id == entry.id)
    ).one()
    assert row.action == "user.role_changed"
    assert row.actor_user_id == actor
    assert (row.object_type, row.object_id) == ("user", "42")
    assert row.summary == summary
    assert row.ip_address == "2001:db8::1"


def test_occurred_at_follows_the_clock_offset(session: Session) -> None:
    """With the clock shifted +1 day, occurred_at is about one day ahead of real UTC."""
    set_offset(timedelta(days=1))

    entry = record(session, action=AuditAction.USER_CREATED)

    # Compare with the database's real time so the check does not use the app clock.
    real_now = session.execute(text("SELECT now()")).scalar_one()
    assert abs(entry.occurred_at - (real_now + timedelta(days=1))) < timedelta(seconds=5)


def test_row_without_actor_or_object_is_allowed(session: Session) -> None:
    """A failed login for an unknown email has no actor or object: the row saves with NULLs."""
    entry = record(session, action=AuditAction.LOGIN_FAILED)

    assert entry.actor_user_id is None
    assert entry.object_type is None
    assert entry.object_id is None
    assert entry.summary is None
    assert entry.ip_address is None


def test_record_does_not_commit(session: Session) -> None:
    """After record() and a rollback with no commit, the audit row is gone."""
    record(session, action=AuditAction.USER_CREATED)
    assert _count_rows(session) == 1

    # The fixture session runs in a SAVEPOINT: a commit inside record() would release it
    # and this rollback would no longer remove the row.
    session.rollback()

    assert _count_rows(session) == 0


def test_update_is_rejected_by_the_trigger(session: Session) -> None:
    """Raw UPDATE of an audit row raises with the append-only trigger message."""
    entry = record(session, action=AuditAction.USER_CREATED)

    with pytest.raises(DBAPIError) as exc:
        session.execute(
            text("UPDATE audit_log SET action = 'x' WHERE id = :id"), {"id": entry.id}
        )

    assert "audit_log is append-only: UPDATE is not allowed" in str(exc.value)


def test_delete_is_rejected_by_the_trigger(session: Session) -> None:
    """Raw DELETE of an audit row raises with the append-only trigger message."""
    record(session, action=AuditAction.USER_CREATED)

    with pytest.raises(DBAPIError) as exc:
        session.execute(text("DELETE FROM audit_log"))

    assert "audit_log is append-only: DELETE is not allowed" in str(exc.value)


def test_truncate_is_rejected_by_the_trigger(session: Session) -> None:
    """TRUNCATE of the audit table raises with the append-only trigger message."""
    record(session, action=AuditAction.USER_CREATED)

    with pytest.raises(DBAPIError) as exc:
        session.execute(text("TRUNCATE audit_log"))

    assert "audit_log is append-only: TRUNCATE is not allowed" in str(exc.value)


@pytest.mark.parametrize(
    "summary",
    [
        {"password_hash": "x"},
        {"change": {"before": {"password_hash": "x"}}},
        {"Token": "x"},
        {"items": [{"session_token": "x"}]},
    ],
    ids=["top-level", "nested", "mixed-case", "inside-list"],
)
def test_forbidden_summary_key_is_rejected(session: Session, summary: dict[str, object]) -> None:
    """A secret-looking summary key (any depth or casing) raises ValueError; no row is added."""
    with pytest.raises(ValueError, match="must not contain the key"):
        record(session, action=AuditAction.USER_CREATED, summary=summary)

    assert _count_rows(session) == 0


def test_unknown_action_string_is_rejected(session: Session) -> None:
    """A mistyped action string ("user.role_change") raises ValueError and inserts nothing."""
    # match= pins the enum's own message, so the forbidden-summary-key ValueError cannot pass.
    with pytest.raises(ValueError, match="not a valid AuditAction"):
        record(session, action="user.role_change")  # type: ignore[arg-type]

    assert _count_rows(session) == 0


@pytest.mark.parametrize("action_value", [action.value for action in AuditAction])
def test_record_accepts_every_vocabulary_value_as_a_string(
    session: Session, action_value: str
) -> None:
    """Checks acceptance of every vocabulary value (not coercion): the stored string matches."""
    entry = record(session, action=action_value)  # type: ignore[arg-type]

    assert entry.action == action_value
    assert _count_rows(session) == 1


def test_audit_actions_are_unique_and_dotted() -> None:
    """AuditAction values are unique and each is lower-case "area.event"."""
    values = [action.value for action in AuditAction]

    assert len(values) == len(set(values))
    for value in values:
        area, dot, event = value.partition(".")
        assert dot == "." and area and event and "." not in event
        assert value == value.lower()


def test_audit_package_is_a_leaf() -> None:
    """No .py file under app/audit imports app.core.models, services or passwords."""
    files = sorted(AUDIT_DIR.rglob("*.py"))
    assert files, "expected audit source files"
    imported: set[str] = set()
    for path in files:
        # Package the file belongs to, e.g. ["app", "audit"]; relative imports resolve against it.
        package = list(path.relative_to(BACKEND_DIR).parent.parts)
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                # level 0 is absolute. For "from ..core import models" (level 2) the base is
                # the package minus one level ("app"), so a relative import cannot hide a
                # forbidden absolute one such as app.core.models.
                base = package[: len(package) - (node.level - 1)] if node.level else []
                parts = base + (node.module.split(".") if node.module else [])
                module = ".".join(parts)
                if module:
                    imported.add(module)
                # "from app.core import models" imports app.core.models too.
                imported.update(f"{module}.{alias.name}" for alias in node.names if module)

    assert imported.isdisjoint(FORBIDDEN_IMPORTS)
