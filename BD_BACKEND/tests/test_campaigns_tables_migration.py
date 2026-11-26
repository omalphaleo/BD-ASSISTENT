"""Test that migration 0010 (the campaigns tables) round-trips cleanly and matches the enums.

Needed because the shared test database is only ever upgraded, so a broken downgrade() in
0010_create_campaigns_tables would go unnoticed; this runs the round trip on its own throwaway
database, checks nothing is seeded, and that each CHECK lists exactly the values of its
Python StrEnum (M1 task B7).
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from app.campaigns.models import (
    CampaignStatus,
    CheckStatus,
    DraftValidationStatus,
    EligibilityResult,
    SequenceStatus,
    ValidatorCheck,
)
from app.content.models import EmailStructureStep

BACKEND_DIR = Path(__file__).resolve().parent.parent

CAMPAIGN_TABLES = (
    "campaigns",
    "campaign_leads",
    "email_sequences",
    "email_drafts",
    "validation_results",
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
    """Return, for each B7 table, whether it exists in the database at url."""
    return {
        table: bool(_scalar(url, f"SELECT to_regclass('public.{table}') IS NOT NULL"))
        for table in CAMPAIGN_TABLES
    }


@pytest.fixture
def roundtrip_url(test_database_url: str) -> Iterator[str]:
    """Create an empty "<name>_campaigns_tables" database, yield its URL, then drop it."""
    # Separate throwaway database: a downgrade on the shared _test database would break
    # the other tests.
    shared_url = make_url(test_database_url)
    name = f"{shared_url.database}_campaigns_tables"
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


def test_campaigns_migration_upgrades_and_downgrades(roundtrip_url: str) -> None:
    """Head has the five tables; downgrade to 0009 removes them; re-upgrade restores them."""
    cfg = alembic_config(roundtrip_url)

    command.upgrade(cfg, "head")
    assert all(_tables_exist(roundtrip_url).values())

    command.downgrade(cfg, "0009")
    assert not any(_tables_exist(roundtrip_url).values())

    command.upgrade(cfg, "head")
    assert all(_tables_exist(roundtrip_url).values())


def test_campaigns_migration_seeds_nothing(roundtrip_url: str) -> None:
    """After upgrade every campaigns table is empty (campaigns are created by M4)."""
    command.upgrade(alembic_config(roundtrip_url), "head")

    for table in CAMPAIGN_TABLES:
        assert _scalar(roundtrip_url, f"SELECT count(*) FROM {table}") == 0, table


def _check_values(engine: Engine, constraint: str) -> set[str]:
    """Return the quoted values listed in the named CHECK constraint."""
    with engine.connect() as conn:
        definition = conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
            {"name": constraint},
        ).scalar_one()
    return set(re.findall(r"'([a-z0-9_]+)'", definition))


@pytest.mark.parametrize(
    ("constraint", "enum_cls"),
    [
        ("ck_campaigns_status_valid", CampaignStatus),
        ("ck_campaign_leads_eligibility_valid", EligibilityResult),
        ("ck_email_sequences_status_valid", SequenceStatus),
        ("ck_email_drafts_step_valid", EmailStructureStep),
        ("ck_email_drafts_validation_valid", DraftValidationStatus),
        ("ck_validation_results_check_id_valid", ValidatorCheck),
        ("ck_validation_results_status_valid", CheckStatus),
    ],
)
def test_checks_list_exactly_the_enum_values(
    migrated_engine: Engine, constraint: str, enum_cls: type
) -> None:
    """Each fixed-value CHECK allows exactly the values of its StrEnum."""
    assert _check_values(migrated_engine, constraint) == {m.value for m in enum_cls}
