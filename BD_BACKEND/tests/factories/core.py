"""Test factories for the core tables: users, sessions, settings, clock offset, job locks.

Needed so tests build valid synthetic core rows in one line and override only the field a
test is about; B's factories and later milestones reuse make_user for foreign keys to users.
All data is synthetic and time comes only from core.clock.now().
"""

import hashlib
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.models import ClockOffset, JobLock, Setting, User, UserRole, UserSession
from factories.common import next_number, persist

# Lifetime of a default session or lock; only has to be in the future relative to creation.
DEFAULT_LIFETIME = timedelta(hours=1)


def make_user(session: Session, **overrides: object) -> User:
    """Insert a rep user with a unique lower-case email and a fake password hash."""
    fields: dict[str, object] = {
        "email": f"rep{next_number()}@example.com",
        "password_hash": "not-a-real-hash",
        "role": UserRole.REP,
    }
    return persist(session, User(**{**fields, **overrides}))


def make_user_session(
    session: Session, *, user: User | None = None, **overrides: object
) -> UserSession:
    """Insert a session for the given user (a new user if none is given), valid for one hour."""
    created_at = now()
    fields: dict[str, object] = {
        "user_id": (user or make_user(session)).id,
        # A real session stores the SHA-256 hex digest (64 characters) of its token.
        "token_hash": hashlib.sha256(f"token-{next_number()}".encode()).hexdigest(),
        "created_at": created_at,
        "expires_at": created_at + DEFAULT_LIFETIME,
    }
    return persist(session, UserSession(**{**fields, **overrides}))


def make_setting(session: Session, **overrides: object) -> Setting:
    """Insert a setting with a unique key and an empty JSON value."""
    fields: dict[str, object] = {"key": f"test.setting_{next_number()}", "value": {}}
    return persist(session, Setting(**{**fields, **overrides}))


def make_clock_offset(session: Session, **overrides: object) -> ClockOffset:
    """Insert the single clock offset row (zero offset).

    The table allows one row and migrations insert none, so call this at most once per test.
    """
    return persist(session, ClockOffset(**overrides))


def make_job_lock(session: Session, **overrides: object) -> JobLock:
    """Insert a job lock with a unique name that expires in one hour."""
    locked_at = now()
    fields: dict[str, object] = {
        "name": f"test.lock_{next_number()}",
        "locked_by": "test-worker",
        "locked_at": locked_at,
        "expires_at": locked_at + DEFAULT_LIFETIME,
    }
    return persist(session, JobLock(**{**fields, **overrides}))
