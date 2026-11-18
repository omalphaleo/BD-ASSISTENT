"""Database engine, per-request session dependency and the SQLAlchemy declarative base.

Needed so every module reaches PostgreSQL through one engine and one Base whose metadata
Alembic migrates; route handlers receive their session via get_session().
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models (models arrive with the data-model task)."""


@lru_cache
def get_engine() -> Engine:
    """Return the shared SQLAlchemy engine, created lazily on first use and cached.

    Raises:
        pydantic.ValidationError: If DATABASE_URL is missing (raised by get_settings()).
    """
    # pool_pre_ping drops connections that went stale (e.g. after a database restart)
    # instead of failing the next request with a broken connection.
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yield one session per request and close it afterwards.

    The session never commits on its own; services decide when to commit.
    """
    # expire_on_commit=False keeps returned objects readable after a commit, so API
    # responses can be built without triggering extra reloads.
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        yield session
