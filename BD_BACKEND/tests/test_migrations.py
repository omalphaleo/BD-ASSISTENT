"""Test that all Alembic migrations apply to an empty database and enable pgvector.

Needed as the "migrations apply on an empty DB" part of the Definition of Done; it runs
the real upgrade path against the throwaway test database from conftest.py.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _config(url: str) -> Config:
    """Build an Alembic Config that targets the given database URL instead of DATABASE_URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # Alembic reads this value through ConfigParser, where a bare % starts interpolation,
    # so any % in the URL (e.g. an encoded password) must be doubled.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def test_migrations_apply_on_empty_db_and_enable_pgvector(test_database_url: str) -> None:
    """Upgrading an empty database to head succeeds and the vector extension is installed."""
    command.upgrade(_config(test_database_url), "head")
    engine = create_engine(test_database_url)
    with engine.connect() as conn:
        found = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar()
    engine.dispose()
    assert found == 1
