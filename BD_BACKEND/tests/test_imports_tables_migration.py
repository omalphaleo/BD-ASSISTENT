"""Test that migration 0007 (the imports tables and the quarantine link) round-trips cleanly.

Needed because the shared test database is only ever upgraded, so a broken downgrade() in
0007_create_imports_tables would go unnoticed; this runs the round trip on its own throwaway
database, checks the migration inserts no rows, that the raw_rows guard is created and removed,
and that the status CHECK lists exactly the values of its Python StrEnum (M1 task A4).
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from app.imports.models import ImportStatus

BACKEND_DIR = Path(__file__).resolve().parent.parent

IMPORTS_TABLES = (
    "source_profiles",
    "import_files",
    "column_mappings",
    "raw_rows",
    "import_reports",
    "import_changes",
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
    """Return, for each A4 table, whether it exists in the database at url."""
    return {
        table: bool(_scalar(url, f"SELECT to_regclass('public.{table}') IS NOT NULL"))
        for table in IMPORTS_TABLES
    }


def _guard_exists(url: str) -> bool:
    """Return True when the raw_rows guard trigger and its function both exist."""
    trigger = _scalar(
        url,
        "SELECT count(*) FROM pg_trigger WHERE tgname = 'raw_rows_guard_original_columns'",
    )
    function = _scalar(
        url,
        "SELECT count(*) FROM pg_proc WHERE proname = 'raw_rows_forbid_original_change'",
    )
    return trigger == 1 and function == 1


def _quarantine_has_raw_row_id(url: str) -> bool:
    """Return True when quarantine_records has the raw_row_id column."""
    return bool(
        _scalar(
            url,
            "SELECT count(*) = 1 FROM information_schema.columns "
            "WHERE table_name = 'quarantine_records' AND column_name = 'raw_row_id'",
        )
    )


@pytest.fixture
def roundtrip_url(test_database_url: str) -> Iterator[str]:
    """Create an empty "<name>_imports_tables" database, yield its URL, then drop it."""
    # Separate throwaway database: a downgrade on the shared _test database would break
    # the other tests. The admin connection uses the shared database, which is a different
    # database from the one being created and dropped.
    shared_url = make_url(test_database_url)
    name = f"{shared_url.database}_imports_tables"
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


def test_imports_migration_upgrades_and_downgrades(roundtrip_url: str) -> None:
    """Head has the tables, guard and quarantine link; downgrade to 0006 removes all of them."""
    cfg = alembic_config(roundtrip_url)

    command.upgrade(cfg, "head")
    assert all(_tables_exist(roundtrip_url).values())
    assert _guard_exists(roundtrip_url)
    assert _quarantine_has_raw_row_id(roundtrip_url)

    command.downgrade(cfg, "0006")
    assert not any(_tables_exist(roundtrip_url).values())
    assert not _guard_exists(roundtrip_url)
    assert not _quarantine_has_raw_row_id(roundtrip_url)

    command.upgrade(cfg, "head")
    assert all(_tables_exist(roundtrip_url).values())


def test_imports_migration_inserts_no_rows(roundtrip_url: str) -> None:
    """After upgrade every imports table is empty: source profiles are not seeded."""
    command.upgrade(alembic_config(roundtrip_url), "head")

    counts = {
        table: _scalar(roundtrip_url, f"SELECT count(*) FROM {table}") for table in IMPORTS_TABLES
    }
    assert set(counts.values()) == {0}


def test_status_check_lists_exactly_the_enum_values(migrated_engine: Engine) -> None:
    """The CHECK in the database allows exactly the ImportStatus values, no more or fewer."""
    with migrated_engine.connect() as conn:
        definition = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_import_files_status_valid'"
            )
        ).scalar_one()

    assert set(re.findall(r"'([a-z_]+)'", definition)) == {m.value for m in ImportStatus}
