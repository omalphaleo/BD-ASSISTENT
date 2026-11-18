"""Audit service: the AuditAction vocabulary and record(), which appends an audit row.

Needed so login and user management can log sensitive actions in one
way. record() only adds and flushes, never commits: the caller's commit makes the audit row
and the action it describes succeed or fail together.
"""

import uuid
from collections.abc import Mapping
from enum import StrEnum

from sqlalchemy.orm import Session

from app.audit.models import AuditLog


class AuditAction(StrEnum):
    """Allowed audit actions, written as "area.event"; extend this as milestones add actions."""

    LOGIN_FAILED = "auth.login_failed"
    LOGIN_THROTTLED = "auth.login_throttled"
    USER_CREATED = "user.created"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_DISABLED = "user.disabled"
    USER_ENABLED = "user.enabled"
    ADMIN_SEEDED = "user.admin_seeded"


# Lower-case names that must never appear as a summary key: secrets do not belong in a
# permanent, append-only log.
FORBIDDEN_SUMMARY_KEYS = frozenset(
    {"password", "password_hash", "token", "token_hash", "session_token"}
)


def _find_forbidden_key(value: object) -> str | None:
    """Return the first forbidden key found in value (dicts and lists, any depth), or None."""
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).lower() in FORBIDDEN_SUMMARY_KEYS:
                return str(key)
            found = _find_forbidden_key(nested)
            if found is not None:
                return found
    elif isinstance(value, list | tuple):
        for item in value:
            found = _find_forbidden_key(item)
            if found is not None:
                return found
    return None


def record(
    db: Session,
    *,
    action: AuditAction,
    actor_user_id: uuid.UUID | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    summary: Mapping[str, object] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Add one audit row to the session and flush it; the caller commits.

    Args:
        db: Session of the caller's transaction.
        action: What happened. A plain string is accepted only if it equals an AuditAction value.
        actor_user_id: The acting user, or None when there is none (e.g. unknown email).
        object_type: Kind of object acted on, if any.
        object_id: Identifier of that object as text, if any.
        summary: Before/after summary, stored as JSON. Values must be JSON-serializable
            (str, int, float, bool, None, list, dict); otherwise the flush fails and the
            caller's transaction is rolled back.
        ip_address: Client IP address as text.

    Returns:
        The flushed AuditLog row (id and occurred_at are set).

    Raises:
        ValueError: If action is not a valid AuditAction value, or if summary contains a
            forbidden key (password, password_hash, token, token_hash, session_token;
            case-insensitive) at any nesting level. Nothing is added in either case.
    """
    # Enforce the vocabulary at runtime: type hints alone would let a typo be stored forever.
    action = AuditAction(action)
    forbidden = _find_forbidden_key(summary)
    if forbidden is not None:
        raise ValueError(f"audit summary must not contain the key {forbidden!r}")
    entry = AuditLog(
        action=action.value,
        actor_user_id=actor_user_id,
        object_type=object_type,
        object_id=object_id,
        summary=dict(summary) if summary is not None else None,
        ip_address=ip_address,
    )
    db.add(entry)
    # flush (not commit): assigns id and occurred_at while the caller keeps the transaction.
    db.flush()
    return entry
