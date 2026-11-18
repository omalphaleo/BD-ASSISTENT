"""Test that the users migration upgrades, downgrades and upgrades again cleanly.

Needed because the shared test database is only ever upgraded, so a broken downgrade() in
0002_create_users would otherwise go unnoticed; this runs the full round trip on its own
throwaway database.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config(url: str) -> Config:
    """Build an Alembic Config that targets the given database URL instead of DATABASE_URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # A bare % would be treated as ConfigParser interpolation, so it is doubled.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _users_table_and_role_type_exist(url: str) -> tuple[bool, bool]:
    """Return (users table exists, user_role enum type exists) for the database at url."""
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            table_exists = conn.execute(text("SELECT to_regclass('public.users') IS NOT NULL"))
            type_exists = conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role')")
            )
            return bool(table_exists.scalar()), bool(type_exists.scalar())
    finally:
        engine.dispose()


@pytest.fixture
def roundtrip_url(test_database_url: str) -> Iterator[str]:
    """Create an empty "<name>_test_roundtrip" database, yield its URL, then drop it."""
    # Separate throwaway database: a downgrade on the shared _test database would break
    # the other tests. The admin connection uses the shared database, which is a different
    # database from the one being created and dropped.
    shared_url = make_url(test_database_url)
    name = f"{shared_url.database}_roundtrip"
    # WITH (FORCE) disconnects any lingering connection so cleanup cannot hang or fail.
    drop_sql = text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    admin = create_engine(shared_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(drop_sql)
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        yield shared_url.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(drop_sql)
        admin.dispose()


def test_users_migration_upgrades_downgrades_and_upgrades_again(roundtrip_url: str) -> None:
    """Upgrade creates the users table and enum, downgrade drops both, re-upgrade restores."""
    cfg = _alembic_config(roundtrip_url)

    command.upgrade(cfg, "head")
    assert _users_table_and_role_type_exist(roundtrip_url) == (True, True)

    command.downgrade(cfg, "0001")
    assert _users_table_and_role_type_exist(roundtrip_url) == (False, False)

    command.upgrade(cfg, "head")
    assert _users_table_and_role_type_exist(roundtrip_url) == (True, True)


def test_downgrade_to_0002_drops_sessions_and_keeps_users(roundtrip_url: str) -> None:
    """Downgrading from head to 0002 removes the sessions table and leaves users in place."""
    cfg = _alembic_config(roundtrip_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0002")

    engine = create_engine(roundtrip_url)
    try:
        with engine.connect() as conn:
            sessions_exists = conn.execute(
                text("SELECT to_regclass('public.sessions') IS NOT NULL")
            ).scalar()
            users_exists = conn.execute(
                text("SELECT to_regclass('public.users') IS NOT NULL")
            ).scalar()
    finally:
        engine.dispose()

    assert (sessions_exists, users_exists) == (False, True)
