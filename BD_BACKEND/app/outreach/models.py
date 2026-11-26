"""SQLAlchemy models for the outreach module: mailboxes, the send queue and send attempts.

Needed so M5 has one persistent outgoing queue (`outreach_messages`, the only way an email
leaves the app) that its scheduler can claim with FOR UPDATE SKIP LOCKED, a `mailboxes` table
that daily and hourly caps count against (D-083), and a record of every send try for the retry
schedule (D-097). Migration 0011 creates the same schema (0012 later adds the thread foreign
key). Tables only in M1 task B8: no scheduler, limits or sender exist yet and nothing is
seeded. Fixed-value columns are VARCHAR plus a named CHECK (not native enums), like the other
modules.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class OutreachMessageStatus(enum.StrEnum):
    """Where a queued email is in its life. The value list is an [ASSUMPTION]: the docs name
    the states (planned, scheduled, sending, deferred, failed, held on pause) but no full list.
    """

    PLANNED = "planned"  # created when the sequence is approved; no concrete send slot yet
    SCHEDULED = "scheduled"  # the scheduler gave it a slot (scheduled_for)
    HELD = "held"  # the campaign is paused; resume re-plans from now (D-015)
    SENDING = "sending"  # claimed by a worker
    SENT = "sent"
    DEFERRED = "deferred"  # a send-time check or cap pushed it back, with a defer_reason
    FAILED = "failed"  # retries used up (30 min, 4 h, 20 h, D-097); the rep is notified
    CANCELLED = "cancelled"  # no longer needed: reply, bounce, opt-out, Qualified (D-082)


class Mailbox(TimestampMixin, Base):
    """A Microsoft 365 mailbox the app sends from. Identifiers only, never credentials."""

    __tablename__ = "mailboxes"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Stored lowercase so the unique constraint cannot be dodged by letter case.
    address: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The rep whose own mailbox this is (D-013). Empty for a shared mailbox (D-002). SET NULL
    # keeps the mailbox, and its history, when the user is deleted.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_mailboxes_owner_id_users"),
        nullable=True,
    )
    # Inactive mailboxes are not used for new sends but keep their history.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    __table_args__ = (
        CheckConstraint("address = lower(address)", name="ck_mailboxes_address_lowercase"),
        UniqueConstraint("address", name="uq_mailboxes_address"),
        Index("ix_mailboxes_owner_id", "owner_id"),
    )


class OutreachMessage(TimestampMixin, Base):
    """One email waiting to be sent, or already sent: the persistent send queue.

    Claiming, limits and retries are M5 service logic; this table holds their state.
    """

    __tablename__ = "outreach_messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    # The approved draft this message sends: at most one message per draft. CASCADE on the
    # links below so erase-person (D-099) and campaign removal leave no orphan queue rows.
    draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_drafts.id", ondelete="CASCADE", name="fk_outreach_messages_draft_id"),
        nullable=False,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE", name="fk_outreach_messages_campaign_id"),
        nullable=False,
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE", name="fk_outreach_messages_person_id_people"),
        nullable=False,
    )
    # The exact address used, so a later change to the person's other addresses is harmless.
    person_email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "person_emails.id",
            ondelete="CASCADE",
            name="fk_outreach_messages_person_email_id_person_emails",
        ),
        nullable=False,
    )
    # RESTRICT: a mailbox with sent history is deactivated, never deleted.
    mailbox_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mailboxes.id", ondelete="RESTRICT", name="fk_outreach_messages_mailbox_id"),
        nullable=False,
    )
    # The mail thread (conversation) this message belongs to. SET NULL keeps the queue row if
    # the thread is removed. The foreign key was added by migration 0012 (task B9).
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mail_threads.id", ondelete="SET NULL", name="fk_outreach_messages_thread_id"),
        nullable=True,
    )
    status: Mapped[OutreachMessageStatus] = mapped_column(
        enum_column(OutreachMessageStatus),
        nullable=False,
        default=OutreachMessageStatus.PLANNED,
        server_default=text("'planned'"),
    )
    # When the plan says it should go out (business-day spacing, D-082) versus the concrete
    # slot the scheduler assigned after the caps and sending window (D-083). UTC.
    planned_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Machine-readable reason a send was pushed back (e.g. "daily_cap"); format check only,
    # because the scheduler that defines the reasons is not built yet.
    defer_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # One key per message, so a retry or a crashed worker can never send twice; the mock
    # Outbox and Microsoft Graph are both keyed on it.
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Which worker holds the row and since when (set together when a worker claims it).
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        in_check("status", OutreachMessageStatus, "ck_outreach_messages_status_valid"),
        CheckConstraint("attempts >= 0", name="ck_outreach_messages_attempts_not_negative"),
        CheckConstraint(
            "defer_reason IS NULL OR defer_reason ~ '^[a-z0-9_]+$'",
            name="ck_outreach_messages_defer_reason_format",
        ),
        # The status must agree with the columns it depends on.
        CheckConstraint(
            "status NOT IN ('scheduled', 'sending', 'sent') OR scheduled_for IS NOT NULL",
            name="ck_outreach_messages_scheduled_has_slot",
        ),
        CheckConstraint(
            "(claimed_by IS NULL) = (claimed_at IS NULL)",
            name="ck_outreach_messages_claim_fields_together",
        ),
        CheckConstraint(
            "status <> 'sending' OR claimed_at IS NOT NULL",
            name="ck_outreach_messages_sending_is_claimed",
        ),
        CheckConstraint(
            "status <> 'deferred' OR defer_reason IS NOT NULL",
            name="ck_outreach_messages_deferred_has_reason",
        ),
        CheckConstraint(
            "status <> 'sent' OR sent_at IS NOT NULL",
            name="ck_outreach_messages_sent_has_time",
        ),
        CheckConstraint(
            "status <> 'failed' OR attempts > 0",
            name="ck_outreach_messages_failed_has_attempts",
        ),
        UniqueConstraint("draft_id", name="uq_outreach_messages_draft_id"),
        UniqueConstraint("idempotency_key", name="uq_outreach_messages_idempotency_key"),
        # The scheduler's per-minute lookup of due messages touches only scheduled rows.
        Index(
            "ix_outreach_messages_due",
            "scheduled_for",
            postgresql_where=text("status = 'scheduled'"),
        ),
        # Daily and hourly caps count a mailbox's messages by time.
        Index("ix_outreach_messages_mailbox_id_scheduled_for", "mailbox_id", "scheduled_for"),
        Index("ix_outreach_messages_campaign_id", "campaign_id"),
        Index("ix_outreach_messages_person_id", "person_id"),
        Index("ix_outreach_messages_person_email_id", "person_email_id"),
        Index("ix_outreach_messages_thread_id", "thread_id"),
    )


class SendAttempt(Base):
    """One try to send a message, kept so retries, errors and timing can be audited (D-097)."""

    __tablename__ = "send_attempts"

    id: Mapped[uuid.UUID] = uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outreach_messages.id", ondelete="CASCADE", name="fk_send_attempts_message_id"),
        nullable=False,
    )
    # 1 for the first try, then +1 (set by the service).
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Short class of the failure, e.g. "throttled"; empty when the attempt succeeded. No
    # message body or recipient data is stored here.
    error_class: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Time comes only from core.clock.now(), so no server-side default.
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("attempt_number >= 1", name="ck_send_attempts_attempt_number_positive"),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_send_attempts_finished_after_started",
        ),
        UniqueConstraint(
            "message_id", "attempt_number", name="uq_send_attempts_message_id_attempt_number"
        ),
    )
