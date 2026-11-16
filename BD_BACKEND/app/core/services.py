"""Session business logic: create, look up and revoke sign-in sessions.

Needed so the future login, logout and current_user code share one tested implementation of
session handling; routes and dependencies (planned) call these functions and never touch
tokens, hashes or the sessions table directly.

Design choices:
- Create and revoke functions commit themselves; lookups are read-only and never commit.
- The raw token (secrets.token_urlsafe) is returned once; only its SHA-256 hex digest is
  stored. The digest is looked up through the unique index, so no constant-time compare is
  needed. Tokens and hashes are never logged or printed.
- Expiry is absolute: a session lives session_lifetime_hours from login. There is no sliding
  renewal; using a session never extends it.
- A session is active only if its hash matches, it is not revoked, it has not expired and
  its user is active, so disabling a user ends their sessions immediately.
- Every time comparison uses core.clock.now() passed as a parameter (never SQL now()), so
  the test clock offset affects expiry.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.clock import now
from app.core.models import User, UserSession

TOKEN_BYTES = 32
# token_urlsafe(32) encodes 32 bytes as 43 URL-safe base64 characters (no padding).
TOKEN_LENGTH = 43


class InactiveUserError(Exception):
    """Raised when a session is requested for a user who is not active."""


@dataclass(frozen=True)
class AuthenticatedSession:
    """The user and session row that a valid token resolves to."""

    user: User
    session: UserSession


def generate_session_token() -> str:
    """Return a new random URL-safe session token (43 characters from a secure source)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """Return the SHA-256 hex digest (64 characters) of a session token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(
    db: Session, user: User, *, lifetime: timedelta | None = None
) -> tuple[str, UserSession]:
    """Create and commit a session for an active user.

    Args:
        db: Database session; committed by this function.
        user: The user signing in.
        lifetime: Time until the session expires; defaults to the configured
            session_lifetime_hours. Expiry is absolute from now, never extended.

    Returns:
        The raw token and the saved session row. The raw token is returned only here and
        is never stored or logged.

    Raises:
        InactiveUserError: If the user is not active (defence in depth; login checks too).
    """
    if not user.is_active:
        raise InactiveUserError("cannot create a session for an inactive user")
    if lifetime is None:
        lifetime = timedelta(hours=get_settings().session_lifetime_hours)

    token = generate_session_token()
    created_at = now()
    row = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        created_at=created_at,
        expires_at=created_at + lifetime,
    )
    db.add(row)
    db.commit()
    return token, row


def get_active_session(db: Session, token: str) -> AuthenticatedSession | None:
    """Return the user and session for a token, or None if it is not an active session.

    Read-only: does not commit and does not extend the session. A token of the wrong length
    is rejected without querying the database.

    Args:
        db: Database session.
        token: The raw token presented by the client.

    Returns:
        AuthenticatedSession if the hash matches, the session is not revoked or expired and
        the user is active; otherwise None.
    """
    if len(token) != TOKEN_LENGTH:
        return None

    # One joined statement so the session and user checks cannot disagree. populate_existing
    # refreshes rows already in the identity map, so role or status changes show immediately.
    statement = (
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.token_hash == hash_session_token(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now(),
            User.is_active.is_(True),
        )
        .execution_options(populate_existing=True)
    )
    row = db.execute(statement).first()
    if row is None:
        return None
    return AuthenticatedSession(user=row.User, session=row.UserSession)


def revoke_session(db: Session, token: str) -> bool:
    """Revoke the session for a token and commit; safe to call repeatedly.

    Args:
        db: Database session; committed by this function.
        token: The raw token to revoke.

    Returns:
        True only if an active session was revoked now; False for an unknown token, a
        wrong-length token or a session that was already revoked.
    """
    if len(token) != TOKEN_LENGTH:
        return False

    # One atomic UPDATE; the revoked_at IS NULL filter keeps the first revocation time.
    statement = (
        update(UserSession)
        .where(
            UserSession.token_hash == hash_session_token(token),
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=now())
        .execution_options(synchronize_session=False)
    )
    result = cast(CursorResult, db.execute(statement))
    db.commit()
    return result.rowcount > 0


def revoke_all_user_sessions(db: Session, user_id: UUID) -> int:
    """Revoke every unrevoked session of one user and commit.

    Already revoked sessions keep their original revoked_at.

    Args:
        db: Database session; committed by this function.
        user_id: The user whose sessions are revoked.

    Returns:
        The number of sessions revoked by this call.
    """
    statement = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now())
        .execution_options(synchronize_session=False)
    )
    result = cast(CursorResult, db.execute(statement))
    db.commit()
    return result.rowcount
