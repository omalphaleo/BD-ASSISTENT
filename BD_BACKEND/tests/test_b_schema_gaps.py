"""Gap tests for B's tables: foreign-key delete rules and behaviours no model test covered.

Needed because the B6-B10 model tests check checks and unique keys but mostly reach the
foreign keys only through a few cascades. This file (M1 task B11) compares every foreign key of
B's tables with the database (ON DELETE rule must equal the model's) and adds the missing
behaviour cases for content, outreach, mail and notifications. Runs against real PostgreSQL
through the shared db_session fixture; all data is synthetic.
"""

import uuid
from collections.abc import Callable

import pytest
from factories import campaigns, content, mail, notifications, outreach
from factories.core import make_user
from factories.leads import make_person_email
from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.campaigns.models import (
    Campaign,
    CampaignLead,
    EmailDraft,
    EmailSequence,
    ValidationResult,
)
from app.content.models import (
    ConfigType,
    ConfigVersion,
    EmailStructure,
    IndustryProfile,
    IndustryProfileItem,
    KnowledgeEmbedding,
    KnowledgeItem,
    StructureSection,
    VoiceSetting,
)
from app.core.models import User
from app.db import Base
from app.leads.models import Person, PersonEmail
from app.mail.models import BounceRecord, InboundMessage, MailThread, ReplyClassification
from app.notifications.models import Notification, SlaReminder
from app.outreach.models import Mailbox, OutreachMessage

Rejected = Callable[[object, str], None]

B_TABLES = frozenset(
    {
        # content
        "voice_settings",
        "size_profiles",
        "industry_profiles",
        "knowledge_items",
        "knowledge_embeddings",
        "industry_profile_items",
        "email_structures",
        "structure_sections",
        "config_versions",
        # campaigns
        "campaigns",
        "campaign_leads",
        "email_sequences",
        "email_drafts",
        "validation_results",
        # outreach
        "mailboxes",
        "outreach_messages",
        "send_attempts",
        # mail
        "mail_threads",
        "outbox_messages",
        "inbound_messages",
        "delta_cursors",
        "reply_classifications",
        "bounce_records",
        # notifications
        "notifications",
        "sla_reminders",
    }
)

# pg_constraint.confdeltype letters mapped to the SQL names SQLAlchemy uses.
DELETE_RULES = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL"}


def _b_foreign_keys() -> list[tuple[str, str, str]]:
    """Return (table, constraint name, expected ON DELETE rule) for every FK of B's tables."""
    found = []
    for table in Base.metadata.sorted_tables:
        if table.name not in B_TABLES:
            continue
        for fk in table.foreign_key_constraints:
            found.append((table.name, fk.name, (fk.ondelete or "NO ACTION").upper()))
    return sorted(found)


B_FOREIGN_KEYS = _b_foreign_keys()


def test_every_listed_b_table_exists_in_the_models() -> None:
    """Every table named in B_TABLES is a real model table (a rename must update the list)."""
    assert B_TABLES <= {table.name for table in Base.metadata.sorted_tables}


@pytest.mark.parametrize(
    ("table", "constraint", "expected_rule"),
    B_FOREIGN_KEYS,
    ids=[f"{t}.{c}" for t, c, _ in B_FOREIGN_KEYS],
)
def test_foreign_key_delete_rule_matches_the_model(
    migrated_engine: Engine, table: str, constraint: str, expected_rule: str
) -> None:
    """Each foreign key exists in the database with the same ON DELETE rule as the model."""
    with migrated_engine.connect() as conn:
        letter = conn.execute(
            text(
                "SELECT confdeltype FROM pg_constraint"
                " WHERE conname = :name AND conrelid = CAST(:table AS regclass)"
            ),
            {"name": constraint, "table": table},
        ).scalar_one()

    assert DELETE_RULES[letter] == expected_rule


# --- content ---


def test_config_version_numbers_are_unique_per_configuration(
    db_session: Session, assert_rejected: Rejected
) -> None:
    """The same version number twice for one configuration is rejected; another may reuse it."""
    first = content.make_config_version(db_session)

    content.make_config_version(db_session)  # another configuration, also version 1
    assert_rejected(
        ConfigVersion(
            config_type=first.config_type,
            config_id=first.config_id,
            version_number=first.version_number,
            snapshot={},
        ),
        "uq_config_versions_config_type_config_id_version_number",
    )


def test_config_version_type_is_part_of_the_unique_key(db_session: Session) -> None:
    """The same config id and number under another config type is a different configuration."""
    first = content.make_config_version(db_session)
    other = content.make_config_version(
        db_session,
        config_type=ConfigType.EMAIL_STRUCTURE,
        config_id=first.config_id,
        version_number=first.version_number,
    )

    assert other.id != first.id


def test_deleting_a_knowledge_item_removes_its_embedding_and_links(db_session: Session) -> None:
    """The embedding and the industry-profile links go with their knowledge item."""
    item = content.make_knowledge_item(db_session)
    content.make_knowledge_embedding(db_session, item=item)
    content.make_industry_profile_item(db_session, item=item)

    db_session.execute(delete(KnowledgeItem).where(KnowledgeItem.id == item.id))

    assert db_session.scalar(select(func.count()).select_from(KnowledgeEmbedding)) == 0
    assert db_session.scalar(select(func.count()).select_from(IndustryProfileItem)) == 0


def test_deleting_an_industry_profile_removes_its_links_but_not_the_items(
    db_session: Session,
) -> None:
    """Deleting a profile removes only the link rows; the knowledge item stays."""
    profile = content.make_industry_profile(db_session)
    link = content.make_industry_profile_item(db_session, profile=profile)

    db_session.execute(delete(IndustryProfile).where(IndustryProfile.id == profile.id))

    assert db_session.scalar(select(func.count()).select_from(IndustryProfileItem)) == 0
    assert db_session.get(KnowledgeItem, link.knowledge_item_id) is not None


def test_deleting_a_structure_removes_its_sections(db_session: Session) -> None:
    """Sections go with their email structure."""
    structure = content.make_email_structure(db_session)
    content.make_structure_section(db_session, structure=structure)

    db_session.execute(delete(EmailStructure).where(EmailStructure.id == structure.id))

    assert db_session.scalar(select(func.count()).select_from(StructureSection)) == 0


def test_knowledge_item_authors_are_set_null_when_users_are_deleted(db_session: Session) -> None:
    """Deleting the creator and approver keeps the item and clears both links."""
    creator, approver = make_user(db_session), make_user(db_session)
    item = content.make_knowledge_item(db_session, created_by=creator.id)
    approved = content.make_knowledge_item(
        db_session,
        status="approved",
        approved_by=approver.id,
        approved_at=item.created_at,
    )

    db_session.execute(delete(User).where(User.id.in_([creator.id, approver.id])))
    db_session.refresh(item)
    db_session.refresh(approved)

    assert item.created_by is None
    assert approved.approved_by is None
    assert approved.approved_at is not None


def test_voice_editor_is_set_null_when_the_user_is_deleted(db_session: Session) -> None:
    """Deleting the admin who last edited the voice keeps the voice and clears the link."""
    editor = make_user(db_session)
    voice = content.make_voice_setting(db_session, updated_by=editor.id)

    db_session.execute(delete(User).where(User.id == editor.id))
    db_session.refresh(voice)

    assert voice.updated_by is None
    assert db_session.scalar(select(func.count()).select_from(VoiceSetting)) == 1


# --- outreach and mail ---


def test_mailbox_owner_foreign_key_rejects_unknown_users(
    db_session: Session, assert_rejected: Rejected
) -> None:
    """A mailbox owned by a user that does not exist violates the foreign key."""
    assert_rejected(
        Mailbox(address="ghost@example.com", owner_id=uuid.uuid4()), "fk_mailboxes_owner_id_users"
    )


def test_deleting_a_campaign_removes_its_queue_rows_and_threads(db_session: Session) -> None:
    """A campaign's queue rows and threads are removed with it."""
    message = outreach.make_outreach_message(db_session)
    mail.make_mail_thread(db_session, campaign=db_session.get(Campaign, message.campaign_id))

    db_session.execute(delete(Campaign).where(Campaign.id == message.campaign_id))

    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == 0
    assert db_session.scalar(select(func.count()).select_from(MailThread)) == 0


def test_deleting_a_person_email_keeps_the_bounce(db_session: Session) -> None:
    """SET NULL: deleting the bounced address keeps the bounce record as evidence."""
    address = make_person_email(db_session)
    bounce = mail.make_bounce_record(db_session, person_email_id=address.id)

    db_session.execute(delete(PersonEmail).where(PersonEmail.id == address.id))
    db_session.refresh(bounce)

    assert bounce.person_email_id is None


def test_deleting_a_reply_removes_its_classification_and_bounce(db_session: Session) -> None:
    """The classification and bounce go with the reply they describe."""
    inbound = mail.make_inbound_message(db_session)
    mail.make_reply_classification(db_session, inbound=inbound)
    mail.make_bounce_record(db_session, inbound=inbound)

    db_session.execute(delete(InboundMessage).where(InboundMessage.id == inbound.id))

    assert db_session.scalar(select(func.count()).select_from(ReplyClassification)) == 0
    assert db_session.scalar(select(func.count()).select_from(BounceRecord)) == 0


# --- notifications ---


def test_notification_survives_when_its_campaign_or_queue_row_is_deleted(
    db_session: Session,
) -> None:
    """SET NULL: deleting the campaign and its queue row keeps the alert, links cleared."""
    message = outreach.make_outreach_message(db_session)
    notification = notifications.make_notification(
        db_session, campaign_id=message.campaign_id, outreach_message_id=message.id
    )

    db_session.execute(delete(Campaign).where(Campaign.id == message.campaign_id))
    db_session.refresh(notification)

    assert notification.campaign_id is None
    assert notification.outreach_message_id is None
    assert db_session.scalar(select(func.count()).select_from(Notification)) == 1


def test_deleting_the_reminded_user_removes_the_reminder(db_session: Session) -> None:
    """The reminder goes with the rep it reminds."""
    user = make_user(db_session)
    notifications.make_sla_reminder(db_session, user=user)

    db_session.execute(delete(User).where(User.id == user.id))

    assert db_session.scalar(select(func.count()).select_from(SlaReminder)) == 0


# --- campaigns ---


def test_deleting_a_person_removes_the_whole_campaign_chain_for_them(db_session: Session) -> None:
    """Erase-person (D-099): leads, sequences, drafts, results, queue rows and threads all go."""
    result = campaigns.make_validation_result(db_session)
    draft = db_session.get(EmailDraft, result.draft_id)
    message = outreach.make_outreach_message(db_session, draft=draft)

    db_session.execute(delete(Person).where(Person.id == message.person_id))

    for model in (CampaignLead, EmailSequence, EmailDraft, ValidationResult, OutreachMessage):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0, model.__name__
