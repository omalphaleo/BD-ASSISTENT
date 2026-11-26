"""Tests for the notifications and sla_reminders tables.

Needed because the schema enforces the alert rules (known types, read time not before creation,
SET NULL on the source pointers, one SLA reminder per reply, a reminder count that matches its
last-reminded time, cascades with the user) until the M6 services exist. Runs against real
PostgreSQL through the shared db_session fixture; all data is synthetic (M1 task B10).
"""

import uuid
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.campaigns.models import Campaign
from app.core.clock import now
from app.core.models import User, UserRole
from app.leads.models import Person
from app.mail.models import InboundMessage, MailThread
from app.notifications.models import Notification, NotificationType, SlaReminder
from app.outreach.models import Mailbox

Rejected = Callable[[object, str], None]


def _token() -> str:
    """Return a unique synthetic value for unique text columns."""
    return uuid.uuid4().hex


def _other_user(db_session: Session) -> User:
    """Insert and return a second user, who can be deleted without touching the fixture user."""
    other = User(email=f"o-{_token()[:8]}@example.com", password_hash="x", role=UserRole.REP)
    db_session.add(other)
    db_session.flush()
    return other


def _inbound(db_session: Session, user: User, person: Person) -> InboundMessage:
    """Insert a mailbox, campaign, thread and one matched reply; return the reply."""
    mailbox = Mailbox(address=f"m-{_token()[:8]}@example.com")
    db_session.add(mailbox)
    db_session.flush()
    campaign = Campaign(name="Q1", owner_id=user.id, sequence_config={}, mailbox_id=mailbox.id)
    db_session.add(campaign)
    db_session.flush()
    thread = MailThread(
        person_id=person.id,
        campaign_id=campaign.id,
        mailbox_id=mailbox.id,
        match_token=_token(),
    )
    db_session.add(thread)
    db_session.flush()
    inbound = InboundMessage(
        thread_id=thread.id,
        mailbox_id=mailbox.id,
        internet_message_id=f"<{_token()}@example.com>",
        received_at=now(),
        from_address="jane@acme.example",
    )
    db_session.add(inbound)
    db_session.flush()
    return inbound


def _notification(user: User, **overrides: object) -> Notification:
    """Build a new-reply notification for the user."""
    values: dict[str, object] = {
        "user_id": user.id,
        "type": NotificationType.NEW_REPLY,
        "title": "Jane Doe replied",
    }
    values.update(overrides)
    return Notification(**values)


# --- notifications ---


def test_notification_defaults(db_session: Session, user: User) -> None:
    """A new notification is unread, not emailed and has no link or source."""
    notification = _notification(user)
    db_session.add(notification)
    db_session.flush()
    db_session.refresh(notification)

    assert notification.read_at is None
    assert notification.emailed_at is None
    assert notification.link is None
    assert notification.inbound_message_id is None
    assert notification.created_at is not None


def test_every_notification_type_is_accepted(db_session: Session, user: User) -> None:
    """All four alert types from the plan can be stored."""
    for kind in NotificationType:
        db_session.add(_notification(user, type=kind))
    db_session.flush()

    count = db_session.scalar(select(func.count()).select_from(Notification))
    assert count == len(NotificationType)


def test_notification_type_must_be_known(user: User, assert_rejected: Rejected) -> None:
    """A type outside the four allowed values is rejected."""
    assert_rejected(_notification(user, type="promo"), "ck_notifications_type_valid")


def test_notification_cannot_be_read_before_it_was_created(
    user: User, assert_rejected: Rejected
) -> None:
    """read_at earlier than created_at is rejected."""
    created = now()

    assert_rejected(
        _notification(user, created_at=created, read_at=created - timedelta(seconds=1)),
        "ck_notifications_read_after_created",
    )


def test_read_notification_is_accepted(db_session: Session, user: User) -> None:
    """A notification read after it was created is valid."""
    created = now()
    notification = _notification(user, created_at=created, read_at=created + timedelta(minutes=5))
    db_session.add(notification)
    db_session.flush()

    assert notification.read_at is not None


def test_notification_requires_an_existing_user(assert_rejected: Rejected) -> None:
    """A notification for a user that does not exist violates the foreign key."""
    assert_rejected(
        Notification(user_id=uuid.uuid4(), type=NotificationType.FAILED_SEND, title="Failed"),
        "fk_notifications_user_id_users",
    )


def test_deleting_a_user_removes_their_notifications(db_session: Session) -> None:
    """Alerts go with the user they were for."""
    other = _other_user(db_session)
    db_session.add(_notification(other))
    db_session.flush()

    db_session.execute(delete(User).where(User.id == other.id))

    assert db_session.scalar(select(func.count()).select_from(Notification)) == 0


def test_notification_survives_when_its_reply_is_deleted(
    db_session: Session, user: User, person: Person
) -> None:
    """SET NULL: deleting the reply keeps the alert and clears the pointer."""
    inbound = _inbound(db_session, user, person)
    notification = _notification(user, inbound_message_id=inbound.id)
    db_session.add(notification)
    db_session.flush()

    db_session.execute(delete(InboundMessage).where(InboundMessage.id == inbound.id))
    db_session.refresh(notification)

    assert notification.inbound_message_id is None


# --- sla_reminders ---


def _reminder(inbound: InboundMessage, user: User, **overrides: object) -> SlaReminder:
    """Build an open SLA reminder for the reply, due in a day."""
    values: dict[str, object] = {
        "inbound_message_id": inbound.id,
        "user_id": user.id,
        "due_at": now() + timedelta(days=1),
    }
    values.update(overrides)
    return SlaReminder(**values)


def test_sla_reminder_defaults(db_session: Session, user: User, person: Person) -> None:
    """A new reminder has been sent zero times, never reminded and is not handled."""
    reminder = _reminder(_inbound(db_session, user, person), user)
    db_session.add(reminder)
    db_session.flush()
    db_session.refresh(reminder)

    assert reminder.reminder_count == 0
    assert reminder.last_reminded_at is None
    assert reminder.handled_at is None


def test_second_reminder_for_a_reply_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A reply has one SLA reminder record."""
    inbound = _inbound(db_session, user, person)
    db_session.add(_reminder(inbound, user))
    db_session.flush()

    assert_rejected(_reminder(inbound, user), "uq_sla_reminders_inbound_message_id")


def test_negative_reminder_count_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A negative reminder count is rejected."""
    inbound = _inbound(db_session, user, person)

    # A last-reminded time keeps the count/time pairing check satisfied, so only the
    # non-negative check can fail.
    assert_rejected(
        _reminder(inbound, user, reminder_count=-1, last_reminded_at=now()),
        "ck_sla_reminders_count_not_negative",
    )


def test_reminder_count_without_a_reminder_time_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A count above zero needs a last-reminded time."""
    inbound = _inbound(db_session, user, person)

    assert_rejected(
        _reminder(inbound, user, reminder_count=1),
        "ck_sla_reminders_count_matches_last_reminded",
    )


def test_reminder_time_without_a_count_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A last-reminded time with a zero count is rejected."""
    inbound = _inbound(db_session, user, person)

    assert_rejected(
        _reminder(inbound, user, last_reminded_at=now()),
        "ck_sla_reminders_count_matches_last_reminded",
    )


def test_reminded_reminder_is_accepted(db_session: Session, user: User, person: Person) -> None:
    """A reminder sent twice with a last-reminded time is valid."""
    inbound = _inbound(db_session, user, person)
    reminder = _reminder(inbound, user, reminder_count=2, last_reminded_at=now())
    db_session.add(reminder)
    db_session.flush()

    assert reminder.reminder_count == 2


def test_deleting_the_reply_removes_its_reminder(
    db_session: Session, user: User, person: Person
) -> None:
    """The reminder goes with the reply it is about."""
    inbound = _inbound(db_session, user, person)
    db_session.add(_reminder(inbound, user))
    db_session.flush()

    db_session.execute(delete(InboundMessage).where(InboundMessage.id == inbound.id))

    assert db_session.scalar(select(func.count()).select_from(SlaReminder)) == 0
