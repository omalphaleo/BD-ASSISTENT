"""SQLAlchemy models for the notifications module: in-app alerts and SLA reminders.

Needed so M6 can alert a rep about a failed send, a new reply, a draft that needs attention or
an overdue follow-up (D-032, D-095, D-097), and track the same-business-day follow-up reminder
per reply. Migration 0013 creates the same schema. Tables only in M1 task B10: no alert
service, email copy or reminder job exists yet and nothing is seeded. Fixed-value columns are
VARCHAR plus a named CHECK (not native enums), like the other modules.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import now
from app.core.model_helpers import TimestampMixin, enum_column, in_check, uuid_pk
from app.db import Base


class NotificationType(enum.StrEnum):
    """The alert kinds named in the plan (section R); the list is an [ASSUMPTION] to confirm."""

    FAILED_SEND = "failed_send"  # retries used up (D-097)
    NEW_REPLY = "new_reply"  # to the sending rep and the lead owner (D-095)
    DRAFT_NEEDS_ATTENTION = "draft_needs_attention"  # validation failed twice (Q-CONTENT-09)
    SLA_REMINDER = "sla_reminder"  # reply not followed up the same business day (D-032)


class Notification(Base):
    """One in-app alert for one user, shown in the bell until it is read."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_notifications_user_id_users"),
        nullable=False,
    )
    type: Mapped[NotificationType] = mapped_column(enum_column(NotificationType), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Where the bell takes the user, e.g. an in-app path; empty when there is nowhere to go.
    link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Optional pointers to what the alert is about. SET NULL keeps the alert if the source row
    # is removed (for example by erase-person).
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL", name="fk_notifications_campaign_id"),
        nullable=True,
    )
    outreach_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "outreach_messages.id",
            ondelete="SET NULL",
            name="fk_notifications_outreach_message_id",
        ),
        nullable=True,
    )
    inbound_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "inbound_messages.id", ondelete="SET NULL", name="fk_notifications_inbound_message_id"
        ),
        nullable=True,
    )
    # Empty while unread.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When the email copy was sent (alerts go in-app and by email, D-017, D-095); empty if not.
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Time comes only from core.clock.now(), so no server-side default.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )

    __table_args__ = (
        in_check("type", NotificationType, "ck_notifications_type_valid"),
        CheckConstraint(
            "read_at IS NULL OR read_at >= created_at", name="ck_notifications_read_after_created"
        ),
        # The bell's "unread" badge and list only look at unread rows of one user.
        Index(
            "ix_notifications_user_id_unread",
            "user_id",
            "created_at",
            postgresql_where=text("read_at IS NULL"),
        ),
        Index("ix_notifications_campaign_id", "campaign_id"),
        Index("ix_notifications_outreach_message_id", "outreach_message_id"),
        Index("ix_notifications_inbound_message_id", "inbound_message_id"),
    )


class SlaReminder(TimestampMixin, Base):
    """The follow-up deadline of one reply and its hourly reminders until handled (D-032)."""

    __tablename__ = "sla_reminders"

    id: Mapped[uuid.UUID] = uuid_pk()
    # One reminder record per reply.
    inbound_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "inbound_messages.id", ondelete="CASCADE", name="fk_sla_reminders_inbound_message_id"
        ),
        nullable=False,
    )
    # The rep being reminded.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_sla_reminders_user_id_users"),
        nullable=False,
    )
    # End of the same business day. How a late-day or weekend reply sets this is an
    # [UNRESOLVED] rule kept in the M6 service, so the table stores only the result.
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_reminded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # Set when the rep marks the reply handled; reminders then stop.
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("reminder_count >= 0", name="ck_sla_reminders_count_not_negative"),
        CheckConstraint(
            "(reminder_count = 0) = (last_reminded_at IS NULL)",
            name="ck_sla_reminders_count_matches_last_reminded",
        ),
        UniqueConstraint("inbound_message_id", name="uq_sla_reminders_inbound_message_id"),
        # The hourly reminder job looks only at reminders that are still open.
        Index("ix_sla_reminders_open_due", "due_at", postgresql_where=text("handled_at IS NULL")),
        Index("ix_sla_reminders_user_id", "user_id"),
    )
