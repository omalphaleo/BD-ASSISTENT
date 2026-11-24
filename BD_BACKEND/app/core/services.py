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

Login and logout also live here. login() gives the same InvalidCredentialsError and
similar timing for an unknown email, a wrong password and a disabled user, and records each
failure in the audit log before raising. It also rejects attempts blocked by the failed-login
limits (core.login_throttle) with that same error.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from functools import cache
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.audit import services as audit
from app.audit.services import AuditAction
from app.config import get_settings
from app.core.clock import now
from app.core.login_throttle import LoginThrottleLimits, ThrottleScope, find_throttle_scope
from app.core.models import User, UserSession
from app.core.passwords import hash_password, password_needs_rehash, verify_password

TOKEN_BYTES = 32
# token_urlsafe(32) encodes 32 bytes as 43 URL-safe base64 characters (no padding).
TOKEN_LENGTH = 43
# Longest valid email address; mirrors users.email String(320). core.schemas reuses this value.
EMAIL_MAX_LENGTH = 320
# Throwaway password for the dummy hash; it only has to cost the same to verify as a real one.
DUMMY_PASSWORD = "not-a-real-password"

# Reasons stored in the audit summary of a failed login (never shown to the client).
REASON_UNKNOWN_USER = "unknown_user"
REASON_BAD_PASSWORD = "bad_password"
REASON_INACTIVE_USER = "inactive_user"


class InactiveUserError(Exception):
    """Raised when a session is requested for a user who is not active."""


class InvalidCredentialsError(Exception):
    """Raised when login fails for any reason (unknown email, wrong password, disabled user)."""


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


def normalize_email(email: str) -> str:
    """Return the email stripped of surrounding whitespace and lower-cased.

    Users are stored lower-case (CHECK ck_users_email_lowercase), so every lookup must
    normalize first; use this function everywhere an email is compared or stored.
    """
    return email.strip().lower()


@cache
def _dummy_password_hash() -> str:
    """Return a hash of a throwaway password, built once per process.

    Verified against when the email is unknown, so that path costs the same Argon2 work as
    a real user's and response time does not reveal which emails exist.
    """
    return hash_password(DUMMY_PASSWORD)


def _record_login_failure(
    db: Session, *, user: User | None, reason: str, normalized_email: str, ip_address: str | None
) -> None:
    """Write one auth.login_failed audit row and commit it.

    The commit happens here (before the caller raises) because the request ends in an
    error response and nothing else would commit; without it the audit row would be lost.
    """
    summary: dict[str, object] = {"reason": reason}
    # People sometimes paste their password into the email field, so a value that does not
    # look like an email (no "@", or too long to be one) is never written to the audit log.
    if "@" in normalized_email and len(normalized_email) <= EMAIL_MAX_LENGTH:
        summary["email_attempted"] = normalized_email
    audit.record(
        db,
        action=AuditAction.LOGIN_FAILED,
        actor_user_id=user.id if user is not None else None,
        object_type="user",
        object_id=str(user.id) if user is not None else None,
        summary=summary,
        ip_address=ip_address,
    )
    db.commit()


def _record_login_throttled(
    db: Session, *, user: User | None, scope: ThrottleScope, ip_address: str | None
) -> None:
    """Write one auth.login_throttled audit row and commit it.

    Deliberately not auth.login_failed: throttled attempts must not count toward the limit,
    or a steady stream of attempts would keep the block alive forever (A9 decision 8). The
    attempted email is not stored, so this row holds no lead or user input.
    """
    audit.record(
        db,
        action=AuditAction.LOGIN_THROTTLED,
        actor_user_id=user.id if user is not None else None,
        object_type="user",
        object_id=str(user.id) if user is not None else None,
        summary={"scope": scope.value},
        ip_address=ip_address,
    )
    db.commit()


def login(
    db: Session,
    email: str,
    password: str,
    *,
    ip_address: str | None,
    lifetime: timedelta | None = None,
    throttle_limits: LoginThrottleLimits | None = None,
) -> tuple[str, User]:
    """Check credentials and start a session.

    Exactly one password verification runs on every path (against the dummy hash when the
    email is unknown), and is_active is checked only after it, so an unknown email, a wrong
    password and a disabled user are indistinguishable by response or timing.

    Throttling (A9): after the verification, an attempt that exceeds the failure limits for
    the account or the client address is rejected with the same error, even when the
    password was correct, so an attacker cannot tell a block from a wrong password.

    Args:
        db: Database session; committed by this function on success and on failure.
        email: The submitted email; normalized here.
        password: The submitted password, used as given.
        ip_address: Client IP for the audit log and the address limit, or None if unknown.
        lifetime: Session lifetime; defaults to the configured session_lifetime_hours.
        throttle_limits: Failure limits; defaults to the documented defaults (5 per account
            and 20 per address in 15 minutes).

    Returns:
        The raw session token (returned only here) and the signed-in user.

    Raises:
        InvalidCredentialsError: For any failure or block, after it was audited and committed.
    """
    normalized = normalize_email(email)
    # Plain equality is safe: the schema guarantees lower-case storage (CHECK constraint).
    user = db.execute(select(User).where(User.email == normalized)).scalar_one_or_none()

    # verify_password takes the hash first, then the plain password.
    password_hash = user.password_hash if user is not None else _dummy_password_hash()
    password_matches = verify_password(password_hash, password)

    # Checked for every attempt, after the verification, so a blocked attempt costs the same
    # as any other and a correct password during a block is still rejected. An unknown email
    # has no user, so only the address limit can block it.
    blocked_by = find_throttle_scope(
        db,
        user_id=user.id if user is not None else None,
        ip_address=ip_address,
        limits=throttle_limits or LoginThrottleLimits(),
    )
    if blocked_by is not None:
        _record_login_throttled(db, user=user, scope=blocked_by, ip_address=ip_address)
        raise InvalidCredentialsError("login throttled")

    if user is None:
        reason = REASON_UNKNOWN_USER
    elif not password_matches:
        reason = REASON_BAD_PASSWORD
    elif not user.is_active:
        reason = REASON_INACTIVE_USER
    else:
        reason = None

    if reason is not None:
        _record_login_failure(
            db, user=user, reason=reason, normalized_email=normalized, ip_address=ip_address
        )
        raise InvalidCredentialsError("login failed")

    # Only reached with a verified password and an active user. Called after a successful
    # verify because password_needs_rehash() raises on a malformed hash.
    if password_needs_rehash(user.password_hash):
        # Upgrade old hashes silently; create_session commits this change with the session.
        user.password_hash = hash_password(password)
    # Marks the point after which failures count again; create_session commits this row too.
    audit.record(
        db,
        action=AuditAction.LOGIN_SUCCEEDED,
        actor_user_id=user.id,
        object_type="user",
        object_id=str(user.id),
        ip_address=ip_address,
    )
    token, _ = create_session(db, user, lifetime=lifetime)
    return token, user


def logout(db: Session, token: str | None) -> None:
    """End the session for a token; safe to call with no, junk or already-revoked tokens.

    Idempotent and never raises for a bad token, so an expired session can still sign out.
    """
    if token:
        revoke_session(db, token)
