from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def test_migrations_apply_on_empty_db_and_enable_pgvector(test_database_url: str) -> None:
    command.upgrade(_config(test_database_url), "head")
    engine = create_engine(test_database_url)
    with engine.connect() as conn:
        found = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar()
    engine.dispose()
    assert found == 1
