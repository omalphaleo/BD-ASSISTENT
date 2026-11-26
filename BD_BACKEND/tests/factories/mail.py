"""Test factories for the mail tables: threads, mock outbox copies, replies, cursors, bounces.

Needed so tests build a valid conversation (thread, queued email, matched reply, its
classification) in one line (M1 task B11). Each factory creates its required parent rows when
none is passed, accepts overrides for any column, and gives every call unique defaults (match
tokens, Message-IDs). All data is synthetic; times come only from core.clock.now().
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.campaigns.models import Campaign
from app.core.clock import now
from app.leads.models import Person
from app.mail.models import (
    BounceKind,
    BounceRecord,
    ClassificationMethod,
    DeltaCursor,
    InboundMessage,
    MailThread,
    OutboxMessage,
    ReplyCategory,
    ReplyClassification,
)
from app.outreach.models import Mailbox, OutreachMessage
from factories.campaigns import make_campaign
from factories.common import next_number, persist
from factories.leads import make_person
from factories.outreach import make_mailbox, make_outreach_message


def make_mail_thread(
    session: Session,
    *,
    person: Person | None = None,
    campaign: Campaign | None = None,
    mailbox: Mailbox | None = None,
    **overrides: object,
) -> MailThread:
    """Insert a thread with no conversation id yet (new person, campaign and mailbox if none)."""
    fields: dict[str, object] = {
        "person_id": (person or make_person(session)).id,
        "campaign_id": (campaign or make_campaign(session)).id,
        "mailbox_id": (mailbox or make_mailbox(session)).id,
        "match_token": f"match-token-{next_number()}",
    }
    return persist(session, MailThread(**{**fields, **overrides}))


def make_outbox_message(
    session: Session, *, message: OutreachMessage | None = None, **overrides: object
) -> OutboxMessage:
    """Insert the mock copy of a queue row (a new queue row if none is given)."""
    number = next_number()
    fields: dict[str, object] = {
        "outreach_message_id": (message or make_outreach_message(session)).id,
        "to_address": f"jane{number}@acme.example",
        "subject": f"Hello {number}",
        "body_html": "<p>Hello</p>",
        "body_text": "Hello",
        "internet_message_id": f"<outbox-{number}@example.com>",
    }
    return persist(session, OutboxMessage(**{**fields, **overrides}))


def make_inbound_message(
    session: Session, *, thread: MailThread | None = None, **overrides: object
) -> InboundMessage:
    """Insert a matched reply on the thread (a new thread if none is given), received now."""
    thread = thread or make_mail_thread(session)
    number = next_number()
    fields: dict[str, object] = {
        "thread_id": thread.id,
        "mailbox_id": thread.mailbox_id,
        "internet_message_id": f"<inbound-{number}@example.com>",
        "received_at": now(),
        "from_address": f"jane{number}@acme.example",
    }
    return persist(session, InboundMessage(**{**fields, **overrides}))


def make_delta_cursor(
    session: Session, *, mailbox: Mailbox | None = None, **overrides: object
) -> DeltaCursor:
    """Insert an empty cursor for the mailbox (a new mailbox if none is given)."""
    fields: dict[str, object] = {"mailbox_id": (mailbox or make_mailbox(session)).id}
    return persist(session, DeltaCursor(**{**fields, **overrides}))


def make_reply_classification(
    session: Session, *, inbound: InboundMessage | None = None, **overrides: object
) -> ReplyClassification:
    """Insert a confident AI "interested" classification of the reply (a new reply if none)."""
    fields: dict[str, object] = {
        "inbound_message_id": (inbound or make_inbound_message(session)).id,
        "category": ReplyCategory.INTERESTED,
        "method": ClassificationMethod.AI,
        "confidence": Decimal("0.91"),
        "model_name": "test-model",
    }
    return persist(session, ReplyClassification(**{**fields, **overrides}))


def make_bounce_record(
    session: Session, *, inbound: InboundMessage | None = None, **overrides: object
) -> BounceRecord:
    """Insert a permanent bounce for the reply (a new reply if none), not linked to a queue row."""
    fields: dict[str, object] = {
        "inbound_message_id": (inbound or make_inbound_message(session)).id,
        "kind": BounceKind.PERMANENT,
    }
    return persist(session, BounceRecord(**{**fields, **overrides}))
