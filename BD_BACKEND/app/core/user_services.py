"""User management business logic: list, create, change role, deactivate and reactivate users.

Needed so the admin user screens and "my profile" share one tested implementation with the
safeguards and audit trail the plan requires (plan.md sections 4 and 14-A, module S). The
routes in core.api call these functions and add nothing; every mutating function re-checks
the MANAGE_USERS capability itself so no other caller can skip it.

Design choices:
- Mutating functions commit themselves, like core.services; the audit row and the change
  are written in the same transaction, so they succeed or fail together.
- Admin safeguards: an admin cannot deactivate or demote themselves, and the last active
  admin can never be deactivated or demoted (the system would lock everyone out of admin).
- Deactivating a user revokes all their sessions in the same transaction.
- Passwords are hashed with the existing Argon2id helper and never stored or logged in clear.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import services as audit
from app.audit.services import AuditAction
from app.core.models import User, UserRole
from app.core.passwords import hash_password
from app.core.permissions import Permission, PermissionDeniedError, has_permission
from app.core.services import normalize_email, revoke_all_user_sessions

OBJECT_TYPE_USER = "user"


class UserManagementError(Exception):
    """Base class for expected, user-facing failures of user management."""


class UserNotFoundError(UserManagementError):
    """Raised when the target user id does not exist."""


class EmailAlreadyExistsError(UserManagementError):
    """Raised when creating a user whose email (case-insensitive) is already taken."""


class SelfModificationError(UserManagementError):
    """Raised when an admin tries to deactivate or demote their own account."""


class LastAdminError(UserManagementError):
    """Raised when a change would leave the system without an active admin."""


def _require_manage_users(actor: User) -> None:
    """Object-level re-check that the acting user may manage users.

    Raises:
        PermissionDeniedError: If the actor's role does not grant MANAGE_USERS.
    """
    if not has_permission(actor, Permission.MANAGE_USERS):
        raise PermissionDeniedError


def _get_user_for_update(db: Session, user_id: uuid.UUID) -> User:
    """Load a user and lock the row so concurrent changes to it are serialised.

    Raises:
        UserNotFoundError: If no user has this id.
    """
    user = db.execute(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if user is None:
        raise UserNotFoundError
    return user


def _lock_active_admin_count(db: Session) -> int:
    """Count active admins while locking their rows.

    The lock makes two admins who deactivate each other at the same moment queue up, so the
    second one sees the first one's result and the last-admin rule cannot be raced.
    """
    admin_ids = db.execute(
        select(User.id)
        .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
        .with_for_update()
    ).all()
    return len(admin_ids)


def _guard_admin_loss(db: Session, actor: User, target: User) -> None:
    """Apply the safeguards for any change that removes an admin's active admin status.

    Raises:
        SelfModificationError: If the actor is the target.
        LastAdminError: If the target is the only active admin.
    """
    if actor.id == target.id:
        raise SelfModificationError
    # Only an active admin counts towards the minimum; others cannot be "the last admin".
    if target.role == UserRole.ADMIN and target.is_active and _lock_active_admin_count(db) <= 1:
        raise LastAdminError


def list_users(db: Session, actor: User) -> list[User]:
    """Return every user, ordered by email.

    Raises:
        PermissionDeniedError: If the actor may not manage users.
    """
    _require_manage_users(actor)
    return list(db.execute(select(User).order_by(User.email)).scalars())


def create_user(
    db: Session,
    actor: User,
    *,
    email: str,
    password: str,
    role: UserRole,
    ip_address: str | None,
) -> User:
    """Create an active user with an admin-provided initial password and audit it.

    Args:
        db: Database session; committed by this function.
        actor: The admin creating the user.
        email: The new user's email; normalized (trimmed, lower-cased) here.
        password: The initial password; hashed with Argon2id, never stored or audited in clear.
        role: The new user's role.
        ip_address: Client IP for the audit log, or None if unknown.

    Returns:
        The saved user.

    Raises:
        PermissionDeniedError: If the actor may not manage users.
        EmailAlreadyExistsError: If the email is already registered (any letter case).
    """
    _require_manage_users(actor)
    normalized = normalize_email(email)
    # Fast check for a friendly error; the unique index still guards the concurrent case below.
    taken = db.execute(
        select(func.count()).select_from(User).where(func.lower(User.email) == normalized)
    ).scalar_one()
    if taken:
        raise EmailAlreadyExistsError

    user = User(email=normalized, password_hash=hash_password(password), role=role)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise EmailAlreadyExistsError from None
    audit.record(
        db,
        action=AuditAction.USER_CREATED,
        actor_user_id=actor.id,
        object_type=OBJECT_TYPE_USER,
        object_id=str(user.id),
        summary={"email": normalized, "role": role.value},
        ip_address=ip_address,
    )
    db.commit()
    return user


def change_role(
    db: Session, actor: User, user_id: uuid.UUID, *, role: UserRole, ip_address: str | None
) -> User:
    """Change a user's role and audit the before and after roles.

    Setting the role a user already has is a no-op: nothing is written or audited.

    Raises:
        PermissionDeniedError: If the actor may not manage users.
        UserNotFoundError: If the user does not exist.
        SelfModificationError: If an admin tries to change their own role.
        LastAdminError: If this would demote the only active admin.
    """
    _require_manage_users(actor)
    target = _get_user_for_update(db, user_id)
    if target.role == role:
        return target
    # Any role change away from admin is "losing an admin"; promotions need no safeguard,
    # but changing your own role is refused in every direction to keep the rule simple.
    if target.role == UserRole.ADMIN:
        _guard_admin_loss(db, actor, target)
    elif actor.id == target.id:
        raise SelfModificationError
    previous_role = target.role
    target.role = role
    audit.record(
        db,
        action=AuditAction.USER_ROLE_CHANGED,
        actor_user_id=actor.id,
        object_type=OBJECT_TYPE_USER,
        object_id=str(target.id),
        summary={"from": previous_role.value, "to": role.value},
        ip_address=ip_address,
    )
    db.commit()
    return target


def deactivate_user(
    db: Session, actor: User, user_id: uuid.UUID, *, ip_address: str | None
) -> User:
    """Deactivate a user, revoke all their sessions and audit it. Idempotent.

    Raises:
        PermissionDeniedError: If the actor may not manage users.
        UserNotFoundError: If the user does not exist.
        SelfModificationError: If an admin tries to deactivate themselves.
        LastAdminError: If the user is the only active admin.
    """
    _require_manage_users(actor)
    target = _get_user_for_update(db, user_id)
    if not target.is_active:
        return target
    _guard_admin_loss(db, actor, target)
    target.is_active = False
    audit.record(
        db,
        action=AuditAction.USER_DISABLED,
        actor_user_id=actor.id,
        object_type=OBJECT_TYPE_USER,
        object_id=str(target.id),
        ip_address=ip_address,
    )
    # Commits the deactivation and the audit row together with the revocations, so a
    # deactivated user can never still hold a working session.
    revoke_all_user_sessions(db, target.id)
    return target


def reactivate_user(
    db: Session, actor: User, user_id: uuid.UUID, *, ip_address: str | None
) -> User:
    """Reactivate a deactivated user and audit it. Idempotent. Old sessions stay revoked.

    Raises:
        PermissionDeniedError: If the actor may not manage users.
        UserNotFoundError: If the user does not exist.
    """
    _require_manage_users(actor)
    target = _get_user_for_update(db, user_id)
    if target.is_active:
        return target
    target.is_active = True
    audit.record(
        db,
        action=AuditAction.USER_ENABLED,
        actor_user_id=actor.id,
        object_type=OBJECT_TYPE_USER,
        object_id=str(target.id),
        ip_address=ip_address,
    )
    db.commit()
    return target
