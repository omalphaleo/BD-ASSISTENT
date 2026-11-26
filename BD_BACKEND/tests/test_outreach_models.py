"""Tests for the mailboxes, outreach_messages and send_attempts tables.

Needed because the schema enforces the queue rules (one message per draft, a unique idempotency
key, a status that always agrees with its claim, slot, reason and time columns, cascades on
erase-person D-099, the campaigns mailbox foreign key) until the M5 scheduler exists. Runs
against real PostgreSQL through the shared db_session fixture; all data is synthetic
(M1 task B8).
"""

import uuid
from collections.abc import Callable
from datetime import timedelta

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
from app.leads.models import EmailType, Person, PersonEmail
from app.outreach.models import Mailbox, OutreachMessage, OutreachMessageStatus, SendAttempt

Rejected = Callable[[object, str], None]


def _mailbox(db_session: Session, address: str = "rep@example.com", **kwargs: object) -> Mailbox:
    """Insert and return a synthetic mailbox."""
    mailbox = Mailbox(address=address, **kwargs)
    db_session.add(mailbox)
    db_session.flush()
    return mailbox


def _chain(
    db_session: Session, user: User, person: Person
) -> tuple[Campaign, EmailDraft, PersonEmail]:
    """Insert a campaign, one sequence draft and the person's work address for a message."""
    campaign = Campaign(name="Q1", owner_id=user.id, sequence_config={"follow_up_1": 3})
    db_session.add(campaign)
    db_session.flush()
    lead = CampaignLead(
        campaign_id=campaign.id, person_id=person.id, eligibility_result=EligibilityResult.ELIGIBLE
    )
    db_session.add(lead)
    db_session.flush()
    sequence = EmailSequence(campaign_lead_id=lead.id)
    db_session.add(sequence)
    db_session.flush()
    draft = EmailDraft(sequence_id=sequence.id, step=EmailStructureStep.FIRST_EMAIL)
    unique_address = f"jane-{uuid.uuid4().hex[:8]}@acme.example"
    address = PersonEmail(
        person_id=person.id,
        # Unique per call: one person can only hold each address once.
        address=unique_address,
        normalized_address=unique_address,
        type=EmailType.WORK,
    )
    db_session.add_all([draft, address])
    db_session.flush()
    return campaign, draft, address


def _message(
    db_session: Session,
    user: User,
    person: Person,
    mailbox: Mailbox | None = None,
    **overrides: object,
) -> OutreachMessage:
    """Insert and return a planned message with its whole chain, applying column overrides."""
    campaign, draft, address = _chain(db_session, user, person)
    values: dict[str, object] = {
        "draft_id": draft.id,
        "campaign_id": campaign.id,
        "person_id": person.id,
        "person_email_id": address.id,
        "mailbox_id": (mailbox or _mailbox(db_session)).id,
        "planned_for": now() + timedelta(days=1),
        "idempotency_key": f"key-{uuid.uuid4()}",
    }
    values.update(overrides)
    message = OutreachMessage(**values)
    db_session.add(message)
    db_session.flush()
    return message


def _rejected_message(
    db_session: Session,
    user: User,
    person: Person,
    assert_rejected: Rejected,
    constraint: str,
    **overrides: object,
) -> None:
    """Assert that a message with the given column overrides violates the named constraint."""
    campaign, draft, address = _chain(db_session, user, person)
    values: dict[str, object] = {
        "draft_id": draft.id,
        "campaign_id": campaign.id,
        "person_id": person.id,
        "person_email_id": address.id,
        "mailbox_id": _mailbox(db_session, f"m-{uuid.uuid4().hex[:8]}@example.com").id,
        "planned_for": now(),
        "idempotency_key": f"key-{uuid.uuid4()}",
    }
    values.update(overrides)
    assert_rejected(OutreachMessage(**values), constraint)


# --- mailboxes ---


def test_mailbox_defaults(db_session: Session) -> None:
    """A new mailbox is active, has no owner and no display name."""
    mailbox = _mailbox(db_session)
    db_session.refresh(mailbox)

    assert mailbox.is_active is True
    assert mailbox.owner_id is None
    assert mailbox.display_name is None


def test_duplicate_mailbox_address_is_rejected(
    db_session: Session, assert_rejected: Rejected
) -> None:
    """Two mailboxes with the same address violate the unique address."""
    _mailbox(db_session, "shared@example.com")

    assert_rejected(Mailbox(address="shared@example.com"), "uq_mailboxes_address")


def test_mailbox_address_must_be_lowercase(assert_rejected: Rejected) -> None:
    """An address with capital letters is rejected so letter case cannot dodge uniqueness."""
    assert_rejected(Mailbox(address="Rep@Example.com"), "ck_mailboxes_address_lowercase")


def test_mailbox_owner_is_set_null_when_user_is_deleted(db_session: Session, user: User) -> None:
    """Deleting the owner keeps the mailbox and clears the owner link."""
    mailbox = _mailbox(db_session, "owned@example.com", owner_id=user.id)

    db_session.execute(delete(User).where(User.id == user.id))
    db_session.refresh(mailbox)

    assert mailbox.owner_id is None


# --- outreach_messages: defaults and uniqueness ---


def test_message_defaults(db_session: Session, user: User, person: Person) -> None:
    """A new message is planned with zero attempts and no slot, claim, thread or reason."""
    message = _message(db_session, user, person)
    db_session.refresh(message)

    assert message.status == OutreachMessageStatus.PLANNED
    assert message.attempts == 0
    assert message.scheduled_for is None
    assert message.claimed_by is None
    assert message.thread_id is None
    assert message.defer_reason is None


def test_second_message_for_a_draft_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A draft is sent by at most one queue row."""
    message = _message(db_session, user, person)

    assert_rejected(
        OutreachMessage(
            draft_id=message.draft_id,
            campaign_id=message.campaign_id,
            person_id=person.id,
            person_email_id=message.person_email_id,
            mailbox_id=message.mailbox_id,
            planned_for=now(),
            idempotency_key="another-key",
        ),
        "uq_outreach_messages_draft_id",
    )


def test_duplicate_idempotency_key_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """Two messages cannot share an idempotency key, so a retry can never send twice."""
    mailbox = _mailbox(db_session)
    _message(db_session, user, person, mailbox, idempotency_key="same-key")

    _rejected_message(
        db_session,
        user,
        person,
        assert_rejected,
        "uq_outreach_messages_idempotency_key",
        idempotency_key="same-key",
    )


def test_message_status_must_be_known(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A status outside the allowed list is rejected."""
    _rejected_message(
        db_session,
        user,
        person,
        assert_rejected,
        "ck_outreach_messages_status_valid",
        status="paused",
    )


# --- outreach_messages: status consistency checks ---


def test_scheduled_message_without_slot_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A scheduled message must have a scheduled_for slot."""
    _rejected_message(
        db_session,
        user,
        person,
        assert_rejected,
        "ck_outreach_messages_scheduled_has_slot",
        status=OutreachMessageStatus.SCHEDULED,
    )


def test_scheduled_message_with_slot_is_accepted(
    db_session: Session, user: User, person: Person
) -> None:
    """A scheduled message with a slot is valid."""
    message = _message(
        db_session,
        user,
        person,
        status=OutreachMessageStatus.SCHEDULED,
        scheduled_for=now() + timedelta(hours=2),
    )

    assert message.status == OutreachMessageStatus.SCHEDULED


def test_sending_message_must_be_claimed(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A sending message with no claim time is rejected."""
    _rejected_message(
        db_session,
        user,
        person,
        assert_rejected,
        "ck_outreach_messages_sending_is_claimed",
        status=OutreachMessageStatus.SENDING,
        scheduled_for=now(),
    )


def test_claim_fields_must_be_set_together(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """claimed_by without claimed_at is rejected."""
    _rejected_message(
        db_session,
        user,
        person,
        assert_rejected,
        "ck_outreach_messages_claim_fields_together",
        claimed_by="worker-1",
    )


def test_claimed_sending_message_is_accepted(
    db_session: Session, user: User, person: Person
) -> None:
    """A sending message with a worker and claim time is valid."""
    message = _message(
        db_session,
        user,
        person,
        status=OutreachMessageStatus.SENDING,
        scheduled_for=now(),
        claimed_by="worker-1",
        claimed_at=now(),
    )

    assert message.claimed_by == "worker-1"


def test_deferred_message_needs_a_reason(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A deferred message with no defer_reason is rejected."""
    _rejected_message(
        db_session,
        user,
        person,
        assert_rejected,
        "ck_outreach_messages_deferred_has_reason",
        status=OutreachMessageStatus.DEFERRED,
    )


def test_defer_reason_must_be_snake_case(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A defer_reason with spaces or capitals is rejected by the format check."""
    _rejected_message(
        db_session,
        user,
        person,
        assert_rejected,
        "ck_outreach_messages_defer_reason_format",
        status=OutreachMessageStatus.DEFERRED,
        defer_reason="Daily Cap",
    )


def test_sent_message_needs_a_sent_time(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A sent message with no sent_at is rejected."""
    _rejected_message(
        db_session,
        user,
        person,
        assert_rejected,
        "ck_outreach_messages_sent_has_time",
        status=OutreachMessageStatus.SENT,
        scheduled_for=now(),
    )


def test_failed_message_needs_attempts(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A failed message with zero attempts is rejected."""
    _rejected_message(
        db_session,
        user,
        person,
        assert_rejected,
        "ck_outreach_messages_failed_has_attempts",
        status=OutreachMessageStatus.FAILED,
    )


def test_negative_attempts_are_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A negative attempt count is rejected."""
    _rejected_message(
        db_session,
        user,
        person,
        assert_rejected,
        "ck_outreach_messages_attempts_not_negative",
        attempts=-1,
    )


# --- outreach_messages: foreign keys ---


def test_deleting_a_mailbox_with_messages_is_blocked(
    db_session: Session, user: User, person: Person
) -> None:
    """RESTRICT: a mailbox that has queued messages cannot be deleted."""
    message = _message(db_session, user, person)

    with (
        pytest.raises(IntegrityError, match="fk_outreach_messages_mailbox_id"),
        db_session.begin_nested(),
    ):
        db_session.execute(delete(Mailbox).where(Mailbox.id == message.mailbox_id))


def test_erasing_a_person_removes_their_messages(
    db_session: Session, user: User, person: Person
) -> None:
    """Erase-person (D-099): deleting the person cascades to their queued messages."""
    _message(db_session, user, person)

    db_session.execute(delete(Person).where(Person.id == person.id))

    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == 0


def test_campaign_mailbox_is_set_null_when_mailbox_is_deleted(
    db_session: Session, user: User
) -> None:
    """The campaigns.mailbox_id foreign key (added in 0011) clears the link on mailbox delete."""
    mailbox = _mailbox(db_session)
    campaign = Campaign(
        name="With mailbox", owner_id=user.id, sequence_config={}, mailbox_id=mailbox.id
    )
    db_session.add(campaign)
    db_session.flush()

    db_session.execute(delete(Mailbox).where(Mailbox.id == mailbox.id))
    db_session.refresh(campaign)

    assert campaign.mailbox_id is None


def test_campaign_requires_an_existing_mailbox(user: User, assert_rejected: Rejected) -> None:
    """A campaign pointing at a mailbox that does not exist violates the foreign key."""
    assert_rejected(
        Campaign(name="Bad", owner_id=user.id, sequence_config={}, mailbox_id=uuid.uuid4()),
        "fk_campaigns_mailbox_id_mailboxes",
    )


# --- send_attempts ---


def test_send_attempt_records_a_failed_try(db_session: Session, user: User, person: Person) -> None:
    """An attempt stores its number and error class; it is unfinished until finished_at is set."""
    message = _message(db_session, user, person)
    attempt = SendAttempt(message_id=message.id, attempt_number=1, error_class="throttled")
    db_session.add(attempt)
    db_session.flush()

    assert attempt.error_class == "throttled"
    assert attempt.finished_at is None
    assert attempt.started_at is not None


def test_duplicate_attempt_number_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A message cannot have two attempts with the same number."""
    message = _message(db_session, user, person)
    db_session.add(SendAttempt(message_id=message.id, attempt_number=1))
    db_session.flush()

    assert_rejected(
        SendAttempt(message_id=message.id, attempt_number=1),
        "uq_send_attempts_message_id_attempt_number",
    )


def test_attempt_number_must_be_positive(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """Attempt number zero is rejected."""
    message = _message(db_session, user, person)

    assert_rejected(
        SendAttempt(message_id=message.id, attempt_number=0),
        "ck_send_attempts_attempt_number_positive",
    )


def test_attempt_cannot_finish_before_it_starts(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """finished_at earlier than started_at is rejected."""
    message = _message(db_session, user, person)
    started = now()

    assert_rejected(
        SendAttempt(
            message_id=message.id,
            attempt_number=1,
            started_at=started,
            finished_at=started - timedelta(seconds=1),
        ),
        "ck_send_attempts_finished_after_started",
    )


def test_deleting_a_message_removes_its_attempts(
    db_session: Session, user: User, person: Person
) -> None:
    """Attempts are removed together with their message."""
    message = _message(db_session, user, person)
    db_session.add(SendAttempt(message_id=message.id, attempt_number=1))
    db_session.flush()

    db_session.execute(delete(OutreachMessage).where(OutreachMessage.id == message.id))

    assert db_session.scalar(select(func.count()).select_from(SendAttempt)) == 0
