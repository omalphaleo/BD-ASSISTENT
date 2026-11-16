"""Test fixtures. Tests run against a real PostgreSQL with pgvector (never SQLite).

DATABASE_URL must point at a reachable server; a separate throwaway database named
"<name>_test" is created on it, so the development database is never touched.
Shared by every database test (migrations, models, health), which receive the URL of the
fresh test database through the test_database_url fixture.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


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
