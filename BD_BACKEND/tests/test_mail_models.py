"""Tests for the mail_threads, outbox_messages, inbound_messages, delta_cursors,
reply_classifications and bounce_records tables.

Needed because the schema enforces the mail rules (unique match token and conversation, one
mock copy per queue row, one stored copy of a polled mail, one classification and one bounce
per reply, a handler only with a handling time, cascades on erase-person D-099, the
outreach_messages.thread_id foreign key) until the M5-M7 services exist. Runs against real
PostgreSQL through the shared db_session fixture; all data is synthetic (M1 task B9).
"""

import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.campaigns.models import (
    Campaign,
    CampaignLead,
    EligibilityResult,
    EmailDraft,
    EmailSequence,
)
from app.content.models import EmailStructureStep
from app.core.clock import now
from app.core.models import User
from app.leads.models import Company, EmailType, Person, PersonEmail
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

Rejected = Callable[[object, str], None]


def _token() -> str:
    """Return a unique synthetic value for unique text columns."""
    return uuid.uuid4().hex


def _mailbox(db_session: Session) -> Mailbox:
    """Insert and return a synthetic mailbox with a unique address."""
    mailbox = Mailbox(address=f"m-{_token()[:8]}@example.com")
    db_session.add(mailbox)
    db_session.flush()
    return mailbox


def _campaign(db_session: Session, user: User, mailbox: Mailbox) -> Campaign:
    """Insert and return a campaign that sends from the given mailbox."""
    campaign = Campaign(name="Q1", owner_id=user.id, sequence_config={}, mailbox_id=mailbox.id)
    db_session.add(campaign)
    db_session.flush()
    return campaign


def _thread(db_session: Session, user: User, person: Person) -> MailThread:
    """Insert and return a thread with its mailbox and campaign."""
    mailbox = _mailbox(db_session)
    campaign = _campaign(db_session, user, mailbox)
    thread = MailThread(
        person_id=person.id,
        campaign_id=campaign.id,
        mailbox_id=mailbox.id,
        match_token=_token(),
    )
    db_session.add(thread)
    db_session.flush()
    return thread


def _queued_message(
    db_session: Session, user: User, person: Person, thread: MailThread
) -> tuple[OutreachMessage, PersonEmail]:
    """Insert a queue row (with its draft chain) that belongs to the given thread."""
    lead = CampaignLead(
        campaign_id=thread.campaign_id,
        person_id=person.id,
        eligibility_result=EligibilityResult.ELIGIBLE,
    )
    db_session.add(lead)
    db_session.flush()
    sequence = EmailSequence(campaign_lead_id=lead.id)
    db_session.add(sequence)
    db_session.flush()
    draft = EmailDraft(sequence_id=sequence.id, step=EmailStructureStep.FIRST_EMAIL)
    address = PersonEmail(
        person_id=person.id,
        address=f"jane-{_token()[:8]}@acme.example",
        normalized_address=f"jane-{_token()[:8]}@acme.example",
        type=EmailType.WORK,
    )
    db_session.add_all([draft, address])
    db_session.flush()
    message = OutreachMessage(
        draft_id=draft.id,
        campaign_id=thread.campaign_id,
        person_id=person.id,
        person_email_id=address.id,
        mailbox_id=thread.mailbox_id,
        thread_id=thread.id,
        planned_for=now(),
        idempotency_key=_token(),
    )
    db_session.add(message)
    db_session.flush()
    return message, address


def _inbound(db_session: Session, thread: MailThread, **overrides: object) -> InboundMessage:
    """Insert and return a matched inbound reply on the thread."""
    values: dict[str, object] = {
        "thread_id": thread.id,
        "mailbox_id": thread.mailbox_id,
        "internet_message_id": f"<{_token()}@example.com>",
        "received_at": now(),
        "from_address": "jane@acme.example",
    }
    values.update(overrides)
    inbound = InboundMessage(**values)
    db_session.add(inbound)
    db_session.flush()
    return inbound


# --- mail_threads ---


def test_thread_defaults(db_session: Session, user: User, person: Person) -> None:
    """A new thread has no conversation id and an empty list of message ids."""
    thread = _thread(db_session, user, person)
    db_session.refresh(thread)

    assert thread.conversation_id is None
    assert thread.internet_message_ids == []


def test_duplicate_match_token_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """Two threads cannot share a match token."""
    thread = _thread(db_session, user, person)

    assert_rejected(
        MailThread(
            person_id=person.id,
            campaign_id=thread.campaign_id,
            mailbox_id=thread.mailbox_id,
            match_token=thread.match_token,
        ),
        "uq_mail_threads_match_token",
    )


def test_conversation_id_is_unique_per_mailbox(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """The same conversation id twice in one mailbox is rejected."""
    thread = _thread(db_session, user, person)
    thread.conversation_id = "AAQkAGI-1"
    db_session.flush()

    assert_rejected(
        MailThread(
            person_id=person.id,
            campaign_id=thread.campaign_id,
            mailbox_id=thread.mailbox_id,
            match_token=_token(),
            conversation_id="AAQkAGI-1",
        ),
        "uq_mail_threads_mailbox_id_conversation_id",
    )


def test_threads_with_unknown_conversation_do_not_clash(
    db_session: Session, user: User, person: Person
) -> None:
    """Several threads in one mailbox may have no conversation id yet (NULLs never clash)."""
    thread = _thread(db_session, user, person)
    other = MailThread(
        person_id=person.id,
        campaign_id=thread.campaign_id,
        mailbox_id=thread.mailbox_id,
        match_token=_token(),
    )
    db_session.add(other)
    db_session.flush()

    assert other.id != thread.id


def test_erasing_a_person_removes_their_threads(
    db_session: Session, user: User, person: Person
) -> None:
    """Erase-person (D-099): deleting the person cascades to their threads."""
    _thread(db_session, user, person)

    db_session.execute(delete(Person).where(Person.id == person.id))

    assert db_session.scalar(select(func.count()).select_from(MailThread)) == 0


def test_deleting_a_mailbox_with_threads_is_blocked(
    db_session: Session, user: User, person: Person
) -> None:
    """RESTRICT: a mailbox that has threads cannot be deleted."""
    thread = _thread(db_session, user, person)

    with (
        pytest.raises(IntegrityError, match="fk_mail_threads_mailbox_id"),
        db_session.begin_nested(),
    ):
        db_session.execute(delete(Mailbox).where(Mailbox.id == thread.mailbox_id))


def test_outreach_message_thread_foreign_key(
    db_session: Session, user: User, person: Person
) -> None:
    """outreach_messages.thread_id (FK added in 0012) is cleared when the thread is deleted."""
    thread = _thread(db_session, user, person)
    message, _ = _queued_message(db_session, user, person, thread)

    db_session.execute(delete(MailThread).where(MailThread.id == thread.id))
    db_session.refresh(message)

    assert message.thread_id is None


def test_outreach_message_requires_an_existing_thread(
    db_session: Session, user: User, person: Person
) -> None:
    """Pointing a queue row at a thread that does not exist violates the foreign key."""
    thread = _thread(db_session, user, person)
    message, _ = _queued_message(db_session, user, person, thread)

    with (
        pytest.raises(IntegrityError, match="fk_outreach_messages_thread_id"),
        db_session.begin_nested(),
    ):
        message.thread_id = uuid.uuid4()
        db_session.flush()


# --- outbox_messages ---


def _outbox(message: OutreachMessage, **overrides: object) -> OutboxMessage:
    """Build a mock outbox copy for the queue row."""
    values: dict[str, object] = {
        "outreach_message_id": message.id,
        "to_address": "jane@acme.example",
        "subject": "Hello",
        "body_html": "<p>Hi</p>",
        "body_text": "Hi",
        "internet_message_id": f"<{_token()}@example.com>",
    }
    values.update(overrides)
    return OutboxMessage(**values)


def test_outbox_defaults(db_session: Session, user: User, person: Person) -> None:
    """A mock copy has empty headers and a creation time set by the clock."""
    thread = _thread(db_session, user, person)
    message, _ = _queued_message(db_session, user, person, thread)
    outbox = _outbox(message)
    db_session.add(outbox)
    db_session.flush()
    db_session.refresh(outbox)

    assert outbox.headers == {}
    assert outbox.created_at is not None


def test_second_outbox_copy_for_a_message_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A queue row has at most one mock copy."""
    thread = _thread(db_session, user, person)
    message, _ = _queued_message(db_session, user, person, thread)
    db_session.add(_outbox(message))
    db_session.flush()

    assert_rejected(_outbox(message), "uq_outbox_messages_outreach_message_id")


def test_duplicate_outbox_message_id_is_rejected(
    db_session: Session, user: User, person: Person, company: Company, assert_rejected: Rejected
) -> None:
    """Two mock copies cannot share a Message-ID."""
    thread = _thread(db_session, user, person)
    first, _ = _queued_message(db_session, user, person, thread)
    # A second recipient: one person can only be selected once per campaign.
    other_person = Person(first_name="Alex", company_id=company.id)
    db_session.add(other_person)
    db_session.flush()
    second, _ = _queued_message(db_session, user, other_person, thread)
    db_session.add(_outbox(first, internet_message_id="<same@example.com>"))
    db_session.flush()

    assert_rejected(
        _outbox(second, internet_message_id="<same@example.com>"),
        "uq_outbox_messages_internet_message_id",
    )


# --- inbound_messages ---


def test_inbound_defaults(db_session: Session, user: User, person: Person) -> None:
    """A stored reply is not simulated by default and has an empty subject and body."""
    inbound = _inbound(db_session, _thread(db_session, user, person))
    db_session.refresh(inbound)

    assert inbound.is_simulated is False
    assert inbound.subject == ""
    assert inbound.body_text == ""
    assert inbound.in_reply_to is None


def test_same_mail_twice_in_a_mailbox_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """Polling the same mail twice cannot store it twice (unique mailbox + Message-ID)."""
    thread = _thread(db_session, user, person)
    inbound = _inbound(db_session, thread)

    assert_rejected(
        InboundMessage(
            thread_id=thread.id,
            mailbox_id=thread.mailbox_id,
            internet_message_id=inbound.internet_message_id,
            received_at=now(),
            from_address="jane@acme.example",
        ),
        "uq_inbound_messages_mailbox_id_message_id",
    )


def test_inbound_requires_a_thread(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """Unmatched mail is not stored: a reply must point at an existing thread."""
    thread = _thread(db_session, user, person)

    assert_rejected(
        InboundMessage(
            thread_id=uuid.uuid4(),
            mailbox_id=thread.mailbox_id,
            internet_message_id=f"<{_token()}@example.com>",
            received_at=now(),
            from_address="jane@acme.example",
        ),
        "fk_inbound_messages_thread_id",
    )


def test_deleting_a_thread_removes_its_replies(
    db_session: Session, user: User, person: Person
) -> None:
    """Replies are removed together with their thread."""
    thread = _thread(db_session, user, person)
    _inbound(db_session, thread)

    db_session.execute(delete(MailThread).where(MailThread.id == thread.id))

    assert db_session.scalar(select(func.count()).select_from(InboundMessage)) == 0


# --- delta_cursors ---


def test_delta_cursor_starts_empty(db_session: Session) -> None:
    """A new cursor has no token and no full-sync time."""
    cursor = DeltaCursor(mailbox_id=_mailbox(db_session).id)
    db_session.add(cursor)
    db_session.flush()

    assert cursor.delta_token is None
    assert cursor.last_full_sync_at is None


def test_second_cursor_for_a_mailbox_is_rejected(
    db_session: Session, assert_rejected: Rejected
) -> None:
    """A mailbox has exactly one delta cursor."""
    mailbox = _mailbox(db_session)
    db_session.add(DeltaCursor(mailbox_id=mailbox.id))
    db_session.flush()

    assert_rejected(DeltaCursor(mailbox_id=mailbox.id), "uq_delta_cursors_mailbox_id")


def test_deleting_a_mailbox_removes_its_cursor(db_session: Session) -> None:
    """The cursor goes with its mailbox."""
    mailbox = _mailbox(db_session)
    db_session.add(DeltaCursor(mailbox_id=mailbox.id))
    db_session.flush()

    db_session.execute(delete(Mailbox).where(Mailbox.id == mailbox.id))

    assert db_session.scalar(select(func.count()).select_from(DeltaCursor)) == 0


# --- reply_classifications ---


def _classification(inbound: InboundMessage, **overrides: object) -> ReplyClassification:
    """Build an AI classification of the reply."""
    values: dict[str, object] = {
        "inbound_message_id": inbound.id,
        "category": ReplyCategory.INTERESTED,
        "method": ClassificationMethod.AI,
        "confidence": Decimal("0.91"),
        "model_name": "test-model",
    }
    values.update(overrides)
    return ReplyClassification(**values)


def test_classification_round_trips_confidence(
    db_session: Session, user: User, person: Person
) -> None:
    """A confidence with two decimals is stored exactly and the reply starts unhandled."""
    inbound = _inbound(db_session, _thread(db_session, user, person))
    classification = _classification(inbound)
    db_session.add(classification)
    db_session.flush()
    db_session.refresh(classification)

    assert classification.confidence == Decimal("0.91")
    assert classification.handled_at is None


def test_classification_without_confidence_is_accepted(
    db_session: Session, user: User, person: Person
) -> None:
    """Rule and manual results carry no confidence."""
    inbound = _inbound(db_session, _thread(db_session, user, person))
    classification = _classification(
        inbound,
        category=ReplyCategory.UNSUBSCRIBE,
        method=ClassificationMethod.RULE,
        confidence=None,
        model_name=None,
    )
    db_session.add(classification)
    db_session.flush()

    assert classification.confidence is None


def test_second_classification_for_a_reply_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A reply has one classification."""
    inbound = _inbound(db_session, _thread(db_session, user, person))
    db_session.add(_classification(inbound))
    db_session.flush()

    assert_rejected(_classification(inbound), "uq_reply_classifications_inbound_message_id")


@pytest.mark.parametrize("confidence", [Decimal("1.50"), Decimal("-0.10")])
def test_confidence_outside_zero_to_one_is_rejected(
    db_session: Session,
    user: User,
    person: Person,
    assert_rejected: Rejected,
    confidence: Decimal,
) -> None:
    """A confidence above 1 or below 0 is rejected."""
    inbound = _inbound(db_session, _thread(db_session, user, person))

    assert_rejected(
        _classification(inbound, confidence=confidence),
        "ck_reply_classifications_confidence_in_range",
    )


def test_category_must_be_known(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A category outside the eight allowed values is rejected."""
    inbound = _inbound(db_session, _thread(db_session, user, person))

    assert_rejected(
        _classification(inbound, category="maybe"), "ck_reply_classifications_category_valid"
    )


def test_handler_without_handling_time_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """handled_by without handled_at is rejected."""
    inbound = _inbound(db_session, _thread(db_session, user, person))

    assert_rejected(
        _classification(inbound, handled_by=user.id), "ck_reply_classifications_handler_has_time"
    )


def test_handler_is_set_null_when_user_is_deleted(
    db_session: Session, user: User, person: Person
) -> None:
    """Deleting the rep who handled a reply keeps the classification and clears the link."""
    inbound = _inbound(db_session, _thread(db_session, user, person))
    # A separate handler: the fixture user owns the campaign (RESTRICT) and cannot be deleted.
    handler = User(email="handler@example.com", password_hash="not-a-real-hash", role=user.role)
    db_session.add(handler)
    db_session.flush()
    classification = _classification(
        inbound, handled_by=handler.id, handled_at=now() + timedelta(minutes=1)
    )
    db_session.add(classification)
    db_session.flush()

    db_session.execute(delete(User).where(User.id == handler.id))
    db_session.refresh(classification)

    assert classification.handled_by is None
    assert classification.handled_at is not None


# --- bounce_records ---


def test_bounce_links_message_and_address(db_session: Session, user: User, person: Person) -> None:
    """A bounce keeps the queue row and address it refers to."""
    thread = _thread(db_session, user, person)
    message, address = _queued_message(db_session, user, person, thread)
    inbound = _inbound(db_session, thread)
    bounce = BounceRecord(
        inbound_message_id=inbound.id,
        outreach_message_id=message.id,
        person_email_id=address.id,
        kind=BounceKind.PERMANENT,
    )
    db_session.add(bounce)
    db_session.flush()

    assert bounce.outreach_message_id == message.id
    assert bounce.person_email_id == address.id


def test_bounce_survives_when_the_queue_row_is_deleted(
    db_session: Session, user: User, person: Person
) -> None:
    """SET NULL: deleting the queue row keeps the bounce as evidence."""
    thread = _thread(db_session, user, person)
    message, _ = _queued_message(db_session, user, person, thread)
    inbound = _inbound(db_session, thread)
    bounce = BounceRecord(
        inbound_message_id=inbound.id,
        outreach_message_id=message.id,
        kind=BounceKind.TEMPORARY,
    )
    db_session.add(bounce)
    db_session.flush()

    db_session.execute(delete(OutreachMessage).where(OutreachMessage.id == message.id))
    db_session.refresh(bounce)

    assert bounce.outreach_message_id is None


def test_second_bounce_for_a_reply_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A bounce notice is recorded once."""
    inbound = _inbound(db_session, _thread(db_session, user, person))
    db_session.add(BounceRecord(inbound_message_id=inbound.id, kind=BounceKind.PERMANENT))
    db_session.flush()

    assert_rejected(
        BounceRecord(inbound_message_id=inbound.id, kind=BounceKind.TEMPORARY),
        "uq_bounce_records_inbound_message_id",
    )


def test_bounce_kind_must_be_known(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A bounce kind outside permanent/temporary is rejected."""
    inbound = _inbound(db_session, _thread(db_session, user, person))

    assert_rejected(
        BounceRecord(inbound_message_id=inbound.id, kind="soft"), "ck_bounce_records_kind_valid"
    )
