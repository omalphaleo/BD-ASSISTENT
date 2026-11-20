"""Test that migration 0006 (the 16 leads tables) upgrades and downgrades cleanly.

Needed because the shared test database is only ever upgraded, so a broken downgrade() in
0006_create_leads_tables would go unnoticed; this runs the round trip on its own throwaway
database, checks the migration inserts no rows, and checks each fixed-value CHECK in the
database lists exactly the values of its Python StrEnum (M1 task A3).
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from app.leads import models as lead_models

BACKEND_DIR = Path(__file__).resolve().parent.parent

LEADS_TABLES = (
    "companies",
    "people",
    "person_emails",
    "person_phones",
    "social_profiles",
    "contact_channels",
    "quarantine_records",
    "duplicate_candidates",
    "merge_records",
    "segments",
    "lead_notes",
    "lead_events",
    "touches",
    "lead_status_flags",
    "industry_mappings",
    "state_mappings",
)

# (constraint name, StrEnum it must mirror) for every fixed-value column.
ENUM_CHECKS = (
    ("ck_person_emails_type_valid", lead_models.EmailType),
    ("ck_person_emails_verification_status_valid", lead_models.EmailVerificationStatus),
    ("ck_contact_channels_channel_type_valid", lead_models.ContactChannelType),
    ("ck_quarantine_records_status_valid", lead_models.QuarantineStatus),
    ("ck_duplicate_candidates_status_valid", lead_models.DuplicateStatus),
    ("ck_segments_visibility_valid", lead_models.SegmentVisibility),
    ("ck_lead_status_flags_flag_type_valid", lead_models.LeadStatusFlagType),
    ("ck_touches_channel_valid", lead_models.TouchChannel),
    ("ck_touches_direction_valid", lead_models.TouchDirection),
    ("ck_touches_status_valid", lead_models.TouchStatus),
)


def alembic_config(url: str) -> Config:
    """Build an Alembic Config that targets the given database URL instead of DATABASE_URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # A bare % would be treated as ConfigParser interpolation, so it is doubled.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _existing_tables(url: str) -> dict[str, bool]:
    """Return, for each A3 table, whether it exists in the database at url."""
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return {
                table: bool(
                    conn.execute(text(f"SELECT to_regclass('public.{table}') IS NOT NULL")).scalar()
                )
                for table in LEADS_TABLES
            }
    finally:
        engine.dispose()


def _row_counts(url: str) -> dict[str, int]:
    """Return the number of rows in each A3 table at url."""
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return {
                table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                for table in LEADS_TABLES
            }
    finally:
        engine.dispose()


@pytest.fixture
def roundtrip_url(test_database_url: str) -> Iterator[str]:
    """Create an empty "<name>_test_leads_tables" database, yield its URL, then drop it."""
    # Separate throwaway database: a downgrade on the shared _test database would break
    # the other tests. The admin connection uses the shared database, which is a different
    # database from the one being created and dropped.
    shared_url = make_url(test_database_url)
    name = f"{shared_url.database}_leads_tables"
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


def test_leads_migration_upgrades_and_downgrades(roundtrip_url: str) -> None:
    """Head has all 16 tables, downgrade to 0005 removes them, re-upgrade restores them."""
    cfg = alembic_config(roundtrip_url)

    command.upgrade(cfg, "head")
    assert all(_existing_tables(roundtrip_url).values())

    command.downgrade(cfg, "0005")
    assert not any(_existing_tables(roundtrip_url).values())

    command.upgrade(cfg, "head")
    assert all(_existing_tables(roundtrip_url).values())


def test_leads_migration_inserts_no_rows(roundtrip_url: str) -> None:
    """After upgrade every leads table is empty: the mapping tables are not seeded."""
    command.upgrade(alembic_config(roundtrip_url), "head")

    assert set(_row_counts(roundtrip_url).values()) == {0}


def test_quarantine_and_link_columns_follow_the_agreed_split(migrated_engine: Engine) -> None:
    """raw_row_id exists since A4's 0007; the B-owned link columns stay plain UUIDs without FKs."""
    with migrated_engine.connect() as conn:
        columns = {
            (table, column)
            for table, column in conn.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public'"
                )
            )
        }
        link_fks = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.key_column_usage "
                "WHERE table_name IN ('touches', 'lead_events') "
                "AND column_name IN ('campaign_id', 'outreach_message_id') "
                "AND constraint_name LIKE 'fk_%'"
            )
        ).scalar_one()

    assert ("quarantine_records", "raw_row_id") in columns
    assert {("touches", "campaign_id"), ("lead_events", "outreach_message_id")} <= columns
    assert link_fks == 0


@pytest.mark.parametrize(("constraint", "enum_cls"), ENUM_CHECKS)
def test_check_constraint_lists_exactly_the_enum_values(
    migrated_engine: Engine, constraint: str, enum_cls: type
) -> None:
    """The CHECK in the database allows exactly the values of its StrEnum, no more or fewer."""
    with migrated_engine.connect() as conn:
        definition = conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
            {"name": constraint},
        ).scalar_one()

    in_database = set(re.findall(r"'([a-z_]+)'", definition))
    assert in_database == {member.value for member in enum_cls}
