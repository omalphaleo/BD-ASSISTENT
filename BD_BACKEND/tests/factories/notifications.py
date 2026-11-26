"""Test factories for the notifications tables: in-app alerts and SLA reminders.

Needed so tests build a valid alert or reminder in one line (M1 task B11). Each factory creates
its required parent rows when none is passed, accepts overrides for any column, and uses only
core.clock.now() for times. All data is synthetic.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.models import User
from app.mail.models import InboundMessage
from app.notifications.models import Notification, NotificationType, SlaReminder
from factories.common import next_number, persist
from factories.core import make_user
from factories.mail import make_inbound_message

# Same-business-day follow-up deadline; the exact rule is the M6 service's (D-032).
DEFAULT_SLA_WINDOW = timedelta(hours=8)


def make_notification(
    session: Session, *, user: User | None = None, **overrides: object
) -> Notification:
    """Insert an unread new-reply alert for the user (a new rep if none is given)."""
    fields: dict[str, object] = {
        "user_id": (user or make_user(session)).id,
        "type": NotificationType.NEW_REPLY,
        "title": f"Reply {next_number()}",
    }
    return persist(session, Notification(**{**fields, **overrides}))


def make_sla_reminder(
    session: Session,
    *,
    inbound: InboundMessage | None = None,
    user: User | None = None,
    **overrides: object,
) -> SlaReminder:
    """Insert an open, never-reminded SLA reminder (new reply and rep if none are given)."""
    fields: dict[str, object] = {
        "inbound_message_id": (inbound or make_inbound_message(session)).id,
        "user_id": (user or make_user(session)).id,
        "due_at": now() + DEFAULT_SLA_WINDOW,
    }
    return persist(session, SlaReminder(**{**fields, **overrides}))
