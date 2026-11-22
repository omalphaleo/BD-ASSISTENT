"""Test fixtures. Tests run against a real PostgreSQL with pgvector (never SQLite).

DATABASE_URL must point at a reachable server; a separate throwaway database named
"<name>_test" is created on it, so the development database is never touched.
Shared by every database test (migrations, models, health), which receive the URL of the
fresh test database through the test_database_url fixture.
"""

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.models import User, UserRole
from app.leads.models import Company, Person

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Create a fresh "<name>_test" database once per run and return its SQLAlchemy URL.

    Fails the run (rather than skipping) if DATABASE_URL is not set, so a misconfigured
    environment can never look like a green test run.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must be set to run the tests (see BD_BACKEND/.env.example)")
    base = make_url(url)
    name = f"{base.database}_test"
    # AUTOCOMMIT: CREATE/DROP DATABASE cannot run inside a transaction block. The admin
    # connection uses the development database only to issue these two statements.
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    return base.set(database=name).render_as_string(hide_password=False)


def alembic_config(url: str) -> Config:
    """Build an Alembic Config that targets the given database URL instead of DATABASE_URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # A bare % would be treated as ConfigParser interpolation, so it is doubled.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="module")
def migrated_engine(test_database_url: str) -> Iterator[Engine]:
    """Migrate the shared test database to head once per module and yield an engine for it."""
    command.upgrade(alembic_config(test_database_url), "head")
    engine = create_engine(test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    """Yield a Session whose work is rolled back after each test.

    The session runs inside an outer transaction and uses SAVEPOINTs, so the constraint
    errors tests provoke do not poison the connection and no row persists between tests.
    """
    with migrated_engine.connect() as connection:
        outer = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            outer.rollback()


@pytest.fixture
def assert_rejected(db_session: Session) -> Callable[[object, str], None]:
    """Return check(row, constraint): adding row must fail on the named database constraint.

    The insert runs in a SAVEPOINT, so the failed statement is undone while rows added
    earlier in the same test (fixtures, other checks) stay in place. A plain
    session.rollback() would also undo those earlier rows.
    """

    def check(row: object, constraint: str) -> None:
        with pytest.raises(IntegrityError, match=constraint), db_session.begin_nested():
            db_session.add(row)
            db_session.flush()

    return check


@pytest.fixture
def user(db_session: Session) -> User:
    """Insert and return a synthetic rep user for foreign keys to users."""
    user = User(email="rep@example.com", password_hash="not-a-real-hash", role=UserRole.REP)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def company(db_session: Session) -> Company:
    """Insert and return a synthetic company."""
    company = Company(name="Acme Test Co", normalized_name="acme test co", domain="acme.example")
    db_session.add(company)
    db_session.flush()
    return company


@pytest.fixture
def person(db_session: Session, company: Company) -> Person:
    """Insert and return a synthetic person who works at the synthetic company."""
    person = Person(first_name="Jane", last_name="Doe", company_id=company.id)
    db_session.add(person)
    db_session.flush()
    return person
