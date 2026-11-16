"""Alembic environment: tells `alembic upgrade/downgrade` which database and models to use.

Needed so migrations run against the same DATABASE_URL as the app (docker-compose runs
`alembic upgrade head` on API start) and so autogenerate sees every model in Base.metadata.
The URL comes from app.config unless one is set on the Alembic Config (tests do this).
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Imported only for its side effect: registering the models on Base.metadata.
import app.core.models  # noqa: F401
from app.config import get_settings
from app.db import Base

config = context.config
if config.config_file_name is not None:
    # Keep the app's own loggers alive when Alembic is run from inside tests.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    """Return the database URL: an explicit Config value first, else the app setting."""
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    """Emit migration SQL as text (`alembic upgrade --sql`) without a database connection."""
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations over a live connection inside a transaction."""
    # NullPool: this is a short-lived CLI run, so no connection is kept open afterwards.
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
