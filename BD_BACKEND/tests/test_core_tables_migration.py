"""Test that migration 0005 (settings, clock_offsets, job_locks) upgrades and downgrades cleanly.

Needed because the shared test database is only ever upgraded, so a broken downgrade() in
0005_create_core_tables would otherwise go unnoticed; this runs the round trip on its own
throwaway database and also checks the migration inserts no rows (decision record 0002).
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
CORE_TABLES = ("settings", "clock_offsets", "job_locks")


def _alembic_config(url: str) -> Config:
    """Build an Alembic Config that targets the given database URL instead of DATABASE_URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # A bare % would be treated as ConfigParser interpolation, so it is doubled.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _existing_core_tables(url: str) -> dict[str, bool]:
    """Return, for each A2 table, whether it exists in the database at url."""
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return {
                table: bool(
                    conn.execute(text(f"SELECT to_regclass('public.{table}') IS NOT NULL")).scalar()
                )
                for table in CORE_TABLES
            }
    finally:
        engine.dispose()


def _row_counts(url: str) -> dict[str, int]:
    """Return the number of rows in each A2 table at url."""
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return {
                table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                for table in CORE_TABLES
            }
    finally:
        engine.dispose()


@pytest.fixture
def roundtrip_url(test_database_url: str) -> Iterator[str]:
    """Create an empty "<name>_test_core_tables" database, yield its URL, then drop it."""
    # Separate throwaway database: a downgrade on the shared _test database would break
    # the other tests. The admin connection uses the shared database, which is a different
    # database from the one being created and dropped.
    shared_url = make_url(test_database_url)
    name = f"{shared_url.database}_core_tables"
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


def test_core_tables_migration_upgrades_and_downgrades(roundtrip_url: str) -> None:
    """Head has all three tables, downgrade to 0004 removes them, re-upgrade restores them."""
    cfg = _alembic_config(roundtrip_url)

    command.upgrade(cfg, "head")
    assert all(_existing_core_tables(roundtrip_url).values())

    command.downgrade(cfg, "0004")
    assert not any(_existing_core_tables(roundtrip_url).values())

    command.upgrade(cfg, "head")
    assert all(_existing_core_tables(roundtrip_url).values())


def test_core_tables_migration_inserts_no_rows(roundtrip_url: str) -> None:
    """After upgrade all three tables are empty: no default settings and no clock row."""
    command.upgrade(_alembic_config(roundtrip_url), "head")

    assert _row_counts(roundtrip_url) == {"settings": 0, "clock_offsets": 0, "job_locks": 0}
