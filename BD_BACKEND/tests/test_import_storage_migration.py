"""Tests for migration 0014 (storage_key and size_bytes on import_files) and its constraints.

Needed because the shared test database is only ever upgraded, so a broken downgrade() in
0014 would go unnoticed; this runs the round trip on its own throwaway database and checks the
model's rules (unique storage_key, non-negative size, NULLs allowed for old rows) against the
real schema. Synthetic rows only.
"""

from collections.abc import Callable, Iterator

import pytest
from alembic import command
from conftest import alembic_config
from factories.imports import make_import_file
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.imports.models import ImportFile

PREVIOUS_REVISION = "0008"


def _import_files_columns(url: str) -> set[str]:
    """Column names of import_files in the database at url."""
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'import_files'"
                )
            )
            return {row[0] for row in rows}
    finally:
        engine.dispose()


@pytest.fixture
def roundtrip_url(test_database_url: str) -> Iterator[str]:
    """Create an empty "<name>_import_storage" database, yield its URL, then drop it."""
    shared_url = make_url(test_database_url)
    name = f"{shared_url.database}_import_storage"
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


def test_storage_columns_are_added_and_removed_by_the_migration(roundtrip_url: str) -> None:
    """Head has both columns; downgrading to 0008 removes them; upgrading restores them."""
    cfg = alembic_config(roundtrip_url)

    command.upgrade(cfg, "head")
    assert {"storage_key", "size_bytes"} <= _import_files_columns(roundtrip_url)

    command.downgrade(cfg, PREVIOUS_REVISION)
    assert not {"storage_key", "size_bytes"} & _import_files_columns(roundtrip_url)

    command.upgrade(cfg, "head")
    assert {"storage_key", "size_bytes"} <= _import_files_columns(roundtrip_url)


def test_rows_without_a_stored_file_are_allowed(db_session: Session) -> None:
    """Old rows keep NULL in both columns, and several of them can coexist (NULLs are distinct)."""
    first = make_import_file(db_session)
    second = make_import_file(db_session)
    assert first.storage_key is None and first.size_bytes is None
    assert second.storage_key is None


def test_storage_key_must_be_unique(
    db_session: Session, assert_rejected: Callable[[object, str], None]
) -> None:
    """Two import files cannot point at the same stored object."""
    key = "a" * 32 + ".csv"
    make_import_file(db_session, storage_key=key, size_bytes=10)
    duplicate = ImportFile(sha256="b" * 64, filename="x.csv", storage_key=key, size_bytes=10)
    assert_rejected(duplicate, "uq_import_files_storage_key")


def test_size_bytes_cannot_be_negative(
    db_session: Session, assert_rejected: Callable[[object, str], None]
) -> None:
    """A negative stored size is rejected by the CHECK constraint."""
    bad = ImportFile(
        sha256="c" * 64, filename="x.csv", storage_key="d" * 32 + ".csv", size_bytes=-1
    )
    assert_rejected(bad, "ck_import_files_size_bytes_nonnegative")


def test_migrated_engine_fixture_is_usable(migrated_engine: Engine) -> None:
    """The shared test database is at head and has the new columns (sanity check)."""
    assert {"storage_key", "size_bytes"} <= _import_files_columns(
        migrated_engine.url.render_as_string(hide_password=False)
    )
