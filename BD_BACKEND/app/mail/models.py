"""SQLAlchemy models for the mail module: threads, mock outbox, inbound replies, cursors, bounces.

Needed so M5 can store the mock Outbox copy of every sent email, M6 can keep matched replies,
their classification and bounces (D-016, D-030, D-094, D-096) and M7 can keep one Microsoft
Graph delta cursor per mailbox. Migration 0012 creates the same schema. Tables only in M1 task
B9: no sender, poller or classifier exists yet and nothing is seeded. Fixed-value columns are
VARCHAR plus a named CHECK (not native enums), like the other modules.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import now
from app.core.model_helpers import TimestampMixin, enum_column, in_check, uuid_pk
from app.db import Base


class ReplyCategory(enum.StrEnum):
    """What a reply is. The six agreed categories (D-030) plus the two safe fallbacks (D-094)."""

    INTERESTED = "interested"
    NOT_NOW = "not_now"
    NOT_INTERESTED = "not_interested"
    OUT_OF_OFFICE = "out_of_office"  # recorded; the sequence continues (D-093)
    WRONG_PERSON = "wrong_person"
    UNSUBSCRIBE = "unsubscribe"
    UNCLEAR = "unclear"  # confidence below the threshold: the rep labels it (D-094)
    UNCLASSIFIED = "unclassified"  # the AI was unavailable: handled like unclear (D-094)


class ClassificationMethod(enum.StrEnum):
    """How a category was decided: fixed keyword rules run before the AI, a rep can relabel."""

    RULE = "rule"
    AI = "ai"
    MANUAL = "manual"


class BounceKind(enum.StrEnum):
    """Permanent bounces invalidate the address at once; temporary ones retry once (D-096)."""

    PERMANENT = "permanent"
    TEMPORARY = "temporary"


class MailThread(TimestampMixin, Base):
    """One conversation with a lead: the outgoing messages and the replies that match it."""

    __tablename__ = "mail_threads"

    id: Mapped[uuid.UUID] = uuid_pk()
    # CASCADE on person and campaign: erase-person (D-099) removes the conversation.
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE", name="fk_mail_threads_person_id_people"),
        nullable=False,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE", name="fk_mail_threads_campaign_id"),
        nullable=False,
    )
    # RESTRICT: a mailbox with threads is deactivated, never deleted.
    mailbox_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mailboxes.id", ondelete="RESTRICT", name="fk_mail_threads_mailbox_id"),
        nullable=False,
    )
    # Microsoft's conversation id; empty until Graph reports it (and always empty in mock mode).
    conversation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The Message-ID values of the thread, used with In-Reply-To / References to match replies.
    internet_message_ids: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # Value of the custom header put on every sent email; the last-resort way to match a reply
    # (reply matching rule 13). Unique so a header value points at exactly one thread.
    match_token: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("match_token", name="uq_mail_threads_match_token"),
        # Graph conversation ids are unique per mailbox; NULLs (not yet known) never clash.
        UniqueConstraint(
            "mailbox_id", "conversation_id", name="uq_mail_threads_mailbox_id_conversation_id"
        ),
        Index("ix_mail_threads_person_id", "person_id"),
        Index("ix_mail_threads_campaign_id", "campaign_id"),
    )


class OutboxMessage(Base):
    """The mock sender's stored copy of an email: exactly what would have been sent."""

    __tablename__ = "outbox_messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    # One copy per queue row; the Outbox viewer lists these.
    outreach_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "outreach_messages.id",
            ondelete="CASCADE",
            name="fk_outbox_messages_outreach_message_id",
        ),
        nullable=False,
    )
    to_address: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Headers the real send would carry, including the custom match header and unsubscribe mailto.
    headers: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # The generated Message-ID, so a simulated reply can point at it with In-Reply-To.
    internet_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Time comes only from core.clock.now(), so no server-side default.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )

    __table_args__ = (
        UniqueConstraint("outreach_message_id", name="uq_outbox_messages_outreach_message_id"),
        UniqueConstraint("internet_message_id", name="uq_outbox_messages_internet_message_id"),
    )


class InboundMessage(Base):
    """A received email that matched a thread. Unmatched mail is dropped, never stored.

    The one exception is an unsubscribe email outside any thread (D-080): it opts the sender
    out directly and stores no row here.
    """

    __tablename__ = "inbound_messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mail_threads.id", ondelete="CASCADE", name="fk_inbound_messages_thread_id"),
        nullable=False,
    )
    mailbox_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mailboxes.id", ondelete="RESTRICT", name="fk_inbound_messages_mailbox_id"),
        nullable=False,
    )
    # The sender's Message-ID: with the mailbox it makes a second poll of the same mail a no-op.
    internet_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    in_reply_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    from_address: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    # Shown on the reply screen next to the thread; replies are answered in Outlook (D-105).
    body_text: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    # True for a reply made with the mock "Simulate reply" screen.
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )

    __table_args__ = (
        UniqueConstraint(
            "mailbox_id", "internet_message_id", name="uq_inbound_messages_mailbox_id_message_id"
        ),
        Index("ix_inbound_messages_thread_id", "thread_id"),
        Index("ix_inbound_messages_mailbox_id_received_at", "mailbox_id", "received_at"),
    )


class DeltaCursor(TimestampMixin, Base):
    """The Microsoft Graph delta token of one mailbox, so each poll reads only new mail."""

    __tablename__ = "delta_cursors"

    id: Mapped[uuid.UUID] = uuid_pk()
    mailbox_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mailboxes.id", ondelete="CASCADE", name="fk_delta_cursors_mailbox_id"),
        nullable=False,
    )
    # Empty before the first poll. An expired or reset token triggers a safe full resync.
    delta_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_full_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (UniqueConstraint("mailbox_id", name="uq_delta_cursors_mailbox_id"),)


class ReplyClassification(TimestampMixin, Base):
    """The category of one reply and whether a rep has handled it (D-094, D-105)."""

    __tablename__ = "reply_classifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    inbound_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "inbound_messages.id",
            ondelete="CASCADE",
            name="fk_reply_classifications_inbound_message_id",
        ),
        nullable=False,
    )
    category: Mapped[ReplyCategory] = mapped_column(enum_column(ReplyCategory), nullable=False)
    method: Mapped[ClassificationMethod] = mapped_column(
        enum_column(ClassificationMethod), nullable=False
    )
    # 0 to 1; empty for rule and manual results. Below the admin threshold (default 0.7) a
    # reply becomes "unclear" (D-094).
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # The rep marks a reply handled after answering it in Outlook (D-105); SET NULL keeps the
    # record when that rep is deleted.
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handled_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_reply_classifications_handled_by"),
        nullable=True,
    )

    __table_args__ = (
        in_check("category", ReplyCategory, "ck_reply_classifications_category_valid"),
        in_check("method", ClassificationMethod, "ck_reply_classifications_method_valid"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_reply_classifications_confidence_in_range",
        ),
        # A handler is only recorded together with the handling time.
        CheckConstraint(
            "handled_by IS NULL OR handled_at IS NOT NULL",
            name="ck_reply_classifications_handler_has_time",
        ),
        UniqueConstraint("inbound_message_id", name="uq_reply_classifications_inbound_message_id"),
        Index("ix_reply_classifications_handled_by", "handled_by"),
    )


class BounceRecord(Base):
    """A bounce notice matched to the email that bounced (D-096)."""

    __tablename__ = "bounce_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    inbound_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "inbound_messages.id", ondelete="CASCADE", name="fk_bounce_records_inbound_message_id"
        ),
        nullable=False,
    )
    # SET NULL on both: the bounce stays as evidence if the queue row or address is removed.
    outreach_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "outreach_messages.id",
            ondelete="SET NULL",
            name="fk_bounce_records_outreach_message_id",
        ),
        nullable=True,
    )
    person_email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "person_emails.id", ondelete="SET NULL", name="fk_bounce_records_person_email_id"
        ),
        nullable=True,
    )
    kind: Mapped[BounceKind] = mapped_column(enum_column(BounceKind), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )

    __table_args__ = (
        in_check("kind", BounceKind, "ck_bounce_records_kind_valid"),
        UniqueConstraint("inbound_message_id", name="uq_bounce_records_inbound_message_id"),
        Index("ix_bounce_records_outreach_message_id", "outreach_message_id"),
        Index("ix_bounce_records_person_email_id", "person_email_id"),
    )
