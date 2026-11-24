"""Login throttling: decides whether a login attempt is blocked by too many recent failures.

Needed so password guessing is slowed down (plan.md section 4, milestone A9) without a new
table: it only counts existing audit rows. core.services.login() calls find_throttle_scope()
on every attempt and turns a block into the same 401 as any other failed login.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.audit.services import AuditAction
from app.config import Settings
from app.core.clock import now

DEFAULT_MAX_FAILURES_PER_ACCOUNT = 5
DEFAULT_MAX_FAILURES_PER_IP = 20
DEFAULT_WINDOW_MINUTES = 15


class ThrottleScope(StrEnum):
    """Which limit blocked an attempt; stored in the audit summary of the throttled row."""

    ACCOUNT = "account"
    IP = "ip"


@dataclass(frozen=True)
class LoginThrottleLimits:
    """How many failed logins are allowed inside the rolling window.

    Attributes:
        max_failures_per_account: Failures for one user (since their last successful login).
        max_failures_per_ip: Failures from one client address, whatever account was tried.
        window: Length of the rolling window; also how long a block lasts at most.
    """

    max_failures_per_account: int = DEFAULT_MAX_FAILURES_PER_ACCOUNT
    max_failures_per_ip: int = DEFAULT_MAX_FAILURES_PER_IP
    window: timedelta = timedelta(minutes=DEFAULT_WINDOW_MINUTES)

    @classmethod
    def from_settings(cls, settings: Settings) -> "LoginThrottleLimits":
        """Build the limits from the configured LOGIN_* environment settings."""
        return cls(
            max_failures_per_account=settings.login_max_failures_per_account,
            max_failures_per_ip=settings.login_max_failures_per_ip,
            window=timedelta(minutes=settings.login_throttle_window_minutes),
        )


def _count_failures_for_user(db: Session, user_id: UUID, window_start: datetime) -> int:
    """Count a user's failed logins newer than the window start and their last success.

    A successful login clears the account's failures (decision 6 of A9), so only failures
    after the latest auth.login_succeeded row count.
    """
    last_success = db.execute(
        select(func.max(AuditLog.occurred_at)).where(
            AuditLog.action == AuditAction.LOGIN_SUCCEEDED.value,
            AuditLog.actor_user_id == user_id,
        )
    ).scalar_one()
    since = window_start if last_success is None else max(window_start, last_success)
    return db.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == AuditAction.LOGIN_FAILED.value,
            AuditLog.actor_user_id == user_id,
            AuditLog.occurred_at > since,
        )
    ).scalar_one()


def _count_failures_for_ip(db: Session, ip_address: str, window_start: datetime) -> int:
    """Count failed logins from one address inside the rolling window (successes ignored)."""
    return db.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == AuditAction.LOGIN_FAILED.value,
            AuditLog.ip_address == ip_address,
            AuditLog.occurred_at > window_start,
        )
    ).scalar_one()


def find_throttle_scope(
    db: Session,
    *,
    user_id: UUID | None,
    ip_address: str | None,
    limits: LoginThrottleLimits,
) -> ThrottleScope | None:
    """Return which limit blocks this attempt, or None if the attempt may proceed.

    Read-only. Blocked attempts are recorded as auth.login_throttled, which is never
    counted here, so a block ends by itself once old failures leave the window.

    Args:
        db: Database session.
        user_id: The account being tried, or None for an unknown email (only the address
            limit can apply then, since there is no account to protect).
        ip_address: Client address, or None if unknown (the address limit is skipped).
        limits: The configured limits.
    """
    window_start = now() - limits.window
    if user_id is not None:
        failures = _count_failures_for_user(db, user_id, window_start)
        if failures >= limits.max_failures_per_account:
            return ThrottleScope.ACCOUNT
    if ip_address is not None:
        if _count_failures_for_ip(db, ip_address, window_start) >= limits.max_failures_per_ip:
            return ThrottleScope.IP
    return None
