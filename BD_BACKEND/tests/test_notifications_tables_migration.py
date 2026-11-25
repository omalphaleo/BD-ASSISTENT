"""Test that migration 0013 (notifications tables) round-trips cleanly and matches the enums.

Needed because the shared test database is only ever upgraded, so a broken downgrade() in
0013_create_notifications_tables would go unnoticed; this runs the round trip on its own throwaway
database, checks nothing is seeded, and that each CHECK lists exactly the values of its
Python StrEnum (M1 task B10).
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from app.notifications.models import NotificationType

BACKEND_DIR = Path(__file__).resolve().parent.parent

NOTIFICATIONS_TABLES = (
    "notifications",
    "sla_reminders",
)


def alembic_config(url: str) -> Config:
    """Build an Alembic Config that targets the given database URL instead of DATABASE_URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # A bare % would be treated as ConfigParser interpolation, so it is doubled.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _scalar(url: str, sql: str) -> object:
    """Run one read-only query against the database at url and return its single value."""
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql)).scalar_one()
    finally:
        engine.dispose()


def _tables_exist(url: str) -> dict[str, bool]:
    """Return, for each B10 table, whether it exists in the database at url."""
    return {
        table: bool(_scalar(url, f"SELECT to_regclass('public.{table}') IS NOT NULL"))
        for table in NOTIFICATIONS_TABLES
    }


@pytest.fixture
def roundtrip_url(test_database_url: str) -> Iterator[str]:
    """Create an empty "<name>_notifications_tables" database, yield its URL, then drop it."""
    # Separate throwaway database: a downgrade on the shared _test database would break
    # the other tests.
    shared_url = make_url(test_database_url)
    name = f"{shared_url.database}_notifications_tables"
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


def test_notifications_migration_upgrades_and_downgrades(roundtrip_url: str) -> None:
    """Head has the 2 tables; downgrade to 0012 removes them; re-upgrade restores them."""
    cfg = alembic_config(roundtrip_url)

    command.upgrade(cfg, "head")
    assert all(_tables_exist(roundtrip_url).values())

    command.downgrade(cfg, "0012")
    assert not any(_tables_exist(roundtrip_url).values())

    command.upgrade(cfg, "head")
    assert all(_tables_exist(roundtrip_url).values())


def test_notifications_migration_seeds_nothing(roundtrip_url: str) -> None:
    """After upgrade every table here is empty (rows are created by later milestones)."""
    command.upgrade(alembic_config(roundtrip_url), "head")

    for table in NOTIFICATIONS_TABLES:
        assert _scalar(roundtrip_url, f"SELECT count(*) FROM {table}") == 0, table


def _check_values(engine: Engine, constraint: str) -> set[str]:
    """Return the quoted values listed in the named CHECK constraint."""
    with engine.connect() as conn:
        definition = conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
            {"name": constraint},
        ).scalar_one()
    return set(re.findall(r"'([a-z0-9_]+)'", definition))


def test_type_check_lists_exactly_the_enum_values(migrated_engine: Engine) -> None:
    """The type CHECK allows exactly the values of NotificationType."""
    assert _check_values(migrated_engine, "ck_notifications_type_valid") == {
        m.value for m in NotificationType
    }
