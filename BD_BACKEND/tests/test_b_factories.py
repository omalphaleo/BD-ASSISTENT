"""Smoke tests for the B-side test factories (content, campaigns, outreach, mail, notifications).

Needed so a factory can never drift away from models.py unnoticed: every factory must insert a
valid row on real PostgreSQL, repeated calls must not collide on a UNIQUE constraint, overrides
must win, and chained factories must build one consistent row chain (M1 task B11). M4 to M6
tests build on these factories.
"""

from collections.abc import Callable

import pytest
from factories import campaigns, content, mail, notifications, outreach
from factories.leads import make_person
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.campaigns.models import CampaignLead, EmailSequence
from app.content.models import (
    EMBEDDING_DIMENSION,
    EmailStructureStep,
    IndustryProfileKey,
    SizeProfileKey,
)
from app.leads.models import PersonEmail
from app.mail.models import MailThread
from app.notifications.models import NotificationType
from app.outreach.models import OutreachMessageStatus

Factory = Callable[[Session], object]

# Factories that insert a new row every call, so they can be called repeatedly in one test.
# The key-limited ones (size and industry profiles, email structures) have enough keys for two.
REPEATABLE_FACTORIES: list[Factory] = [
    content.make_size_profile,
    content.make_industry_profile,
    content.make_knowledge_item,
    content.make_knowledge_embedding,
    content.make_industry_profile_item,
    content.make_email_structure,
    content.make_structure_section,
    content.make_config_version,
    campaigns.make_campaign,
    campaigns.make_campaign_lead,
    campaigns.make_email_sequence,
    campaigns.make_email_draft,
    campaigns.make_validation_result,
    outreach.make_mailbox,
    outreach.make_outreach_message,
    outreach.make_send_attempt,
    mail.make_mail_thread,
    mail.make_outbox_message,
    mail.make_inbound_message,
    mail.make_delta_cursor,
    mail.make_reply_classification,
    mail.make_bounce_record,
    notifications.make_notification,
    notifications.make_sla_reminder,
]


@pytest.mark.parametrize("factory", REPEATABLE_FACTORIES, ids=lambda f: f.__name__)
def test_factory_inserts_distinct_valid_rows(db_session: Session, factory: Factory) -> None:
    """Calling a factory twice inserts two persisted rows with different keys and no error."""
    first = factory(db_session)
    second = factory(db_session)
    # The primary-key identity also works for the link table, whose key has two columns.
    assert inspect(first).identity is not None
    assert inspect(first).identity != inspect(second).identity


def test_voice_factory_returns_the_single_voice_row(db_session: Session) -> None:
    """The voice is a single row: a second call returns the same row instead of failing."""
    first = content.make_voice_setting(db_session, tone="warm")
    second = content.make_voice_setting(db_session, tone="ignored")

    assert second.id == first.id
    assert second.tone == "warm"


# --- overrides ---


def test_overrides_win_over_defaults(db_session: Session) -> None:
    """A value passed to a factory replaces its default."""
    message = outreach.make_outreach_message(
        db_session, status=OutreachMessageStatus.CANCELLED, idempotency_key="my-key"
    )
    notification = notifications.make_notification(
        db_session, type=NotificationType.FAILED_SEND, title="Send failed"
    )

    assert message.status == OutreachMessageStatus.CANCELLED
    assert message.idempotency_key == "my-key"
    assert notification.type == NotificationType.FAILED_SEND
    assert notification.title == "Send failed"


# --- fixed-key tables ---


def test_profile_factories_use_distinct_keys(db_session: Session) -> None:
    """Successive profile and structure factories take the next unused key."""
    sizes = [content.make_size_profile(db_session).key for _ in range(3)]
    industries = [content.make_industry_profile(db_session).key for _ in range(2)]
    steps = [content.make_email_structure(db_session).step for _ in range(3)]

    assert sizes == list(SizeProfileKey)
    assert industries == list(IndustryProfileKey)[:2]
    assert steps == list(EmailStructureStep)


def test_key_factory_raises_when_every_key_is_used(db_session: Session) -> None:
    """A fourth size profile has no key left, so the factory says so instead of a DB error."""
    for _ in SizeProfileKey:
        content.make_size_profile(db_session)

    with pytest.raises(RuntimeError, match="keys are already used"):
        content.make_size_profile(db_session)


def test_embedding_has_the_configured_dimension(db_session: Session) -> None:
    """The default vector has exactly EMBEDDING_DIMENSION values and a matching dimension."""
    embedding = content.make_knowledge_embedding(db_session)
    db_session.refresh(embedding)

    assert len(embedding.embedding) == EMBEDDING_DIMENSION
    assert embedding.dimension == EMBEDDING_DIMENSION


def test_sections_get_consecutive_positions(db_session: Session) -> None:
    """Sections of one structure are numbered 1, 2, 3 in creation order."""
    structure = content.make_email_structure(db_session)
    positions = [
        content.make_structure_section(db_session, structure=structure).position for _ in range(3)
    ]

    assert positions == [1, 2, 3]


# --- parents are created or reused ---


def test_factories_reuse_a_passed_parent(db_session: Session) -> None:
    """Passing a parent makes the factory attach to it instead of creating another one."""
    campaign = campaigns.make_campaign(db_session)
    person = make_person(db_session)
    lead = campaigns.make_campaign_lead(db_session, campaign=campaign, person=person)
    sequence = campaigns.make_email_sequence(db_session, campaign_lead=lead)
    draft = campaigns.make_email_draft(db_session, sequence=sequence)

    assert lead.campaign_id == campaign.id
    assert lead.person_id == person.id
    assert sequence.campaign_lead_id == lead.id
    assert draft.sequence_id == sequence.id


def test_queue_row_is_consistent_with_its_draft_chain(db_session: Session) -> None:
    """The queue row's campaign, person and address all belong to the draft it sends."""
    draft = campaigns.make_email_draft(db_session)
    message = outreach.make_outreach_message(db_session, draft=draft)

    sequence = db_session.get(EmailSequence, draft.sequence_id)
    lead = db_session.get(CampaignLead, sequence.campaign_lead_id)
    address = db_session.get(PersonEmail, message.person_email_id)
    assert message.draft_id == draft.id
    assert message.campaign_id == lead.campaign_id
    assert message.person_id == lead.person_id
    assert address.person_id == lead.person_id


def test_mail_factories_share_the_thread_mailbox(db_session: Session) -> None:
    """A reply made for a thread is stored in that thread's mailbox."""
    thread = mail.make_mail_thread(db_session)
    inbound = mail.make_inbound_message(db_session, thread=thread)

    assert inbound.thread_id == thread.id
    assert inbound.mailbox_id == thread.mailbox_id
    assert db_session.scalar(select(MailThread.id).where(MailThread.id == thread.id)) is not None


def test_sla_reminder_is_open_and_not_yet_reminded(db_session: Session) -> None:
    """The default reminder has no reminders sent and is not handled."""
    reminder = notifications.make_sla_reminder(db_session)

    assert reminder.reminder_count == 0
    assert reminder.last_reminded_at is None
    assert reminder.handled_at is None
