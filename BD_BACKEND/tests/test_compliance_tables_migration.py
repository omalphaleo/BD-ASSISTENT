"""Test that migration 0008 (the compliance tables and their seed rows) round-trips cleanly.

Needed because the shared test database is only ever upgraded, so a broken downgrade() in
0008_create_compliance_tables would go unnoticed; this runs the round trip on its own
throwaway database, checks exactly the expected seed rows exist, and that the CHECKs list
exactly the values of their Python StrEnums (M1 task A5).
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from app.compliance.models import ChecklistItemKey, OptOutSource

BACKEND_DIR = Path(__file__).resolve().parent.parent

COMPLIANCE_TABLES = (
    "opt_outs",
    "compliance_gate_status",
    "compliance_checklist_items",
    "erasure_records",
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
    """Return, for each A5 table, whether it exists in the database at url."""
    return {
        table: bool(_scalar(url, f"SELECT to_regclass('public.{table}') IS NOT NULL"))
        for table in COMPLIANCE_TABLES
    }


@pytest.fixture
def roundtrip_url(test_database_url: str) -> Iterator[str]:
    """Create an empty "<name>_compliance_tables" database, yield its URL, then drop it."""
    # Separate throwaway database: a downgrade on the shared _test database would break
    # the other tests.
    shared_url = make_url(test_database_url)
    name = f"{shared_url.database}_compliance_tables"
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


def test_compliance_migration_upgrades_and_downgrades(roundtrip_url: str) -> None:
    """Head has the four tables; downgrade to 0007 removes them; re-upgrade restores them."""
    cfg = alembic_config(roundtrip_url)

    command.upgrade(cfg, "head")
    assert all(_tables_exist(roundtrip_url).values())

    command.downgrade(cfg, "0007")
    assert not any(_tables_exist(roundtrip_url).values())

    command.upgrade(cfg, "head")
    assert all(_tables_exist(roundtrip_url).values())


def test_compliance_migration_seeds_only_gate_and_checklist(roundtrip_url: str) -> None:
    """After upgrade the gate has one disabled row, the checklist four rows; others are empty."""
    command.upgrade(alembic_config(roundtrip_url), "head")

    def count(table: str) -> object:
        return _scalar(roundtrip_url, f"SELECT count(*) FROM {table}")

    assert count("compliance_gate_status") == 1
    assert count("compliance_checklist_items") == 4
    assert count("opt_outs") == 0
    assert count("erasure_records") == 0
    assert (
        _scalar(
            roundtrip_url,
            "SELECT real_sending_enabled FROM compliance_gate_status",
        )
        is False
    )


def _check_values(engine: Engine, constraint: str) -> set[str]:
    """Return the quoted values listed in the named CHECK constraint."""
    with engine.connect() as conn:
        definition = conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
            {"name": constraint},
        ).scalar_one()
    return set(re.findall(r"'([a-z0-9_]+)'", definition))


def test_checks_list_exactly_the_enum_values(migrated_engine: Engine) -> None:
    """The source and item_key CHECKs allow exactly the values of their StrEnums."""
    assert _check_values(migrated_engine, "ck_opt_outs_source_valid") == {
        m.value for m in OptOutSource
    }
    assert _check_values(migrated_engine, "ck_compliance_checklist_items_item_key_valid") == {
        m.value for m in ChecklistItemKey
    }
