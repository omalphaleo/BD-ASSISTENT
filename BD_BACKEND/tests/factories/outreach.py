"""Test factories for the outreach tables: mailboxes, the send queue and send attempts.

Needed so tests build a valid queued email (with its draft, lead, address and mailbox) in one
line (M1 task B11). A queue row is built from the chain of its draft, so its campaign, person
and recipient address always belong together. All data is synthetic; times come only from
core.clock.now().
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.campaigns.models import CampaignLead, EmailDraft, EmailSequence
from app.core.clock import now
from app.core.models import User
from app.leads.models import Person
from app.outreach.models import Mailbox, OutreachMessage, SendAttempt
from factories.campaigns import make_email_draft
from factories.common import next_number, persist
from factories.leads import make_person_email

# How far ahead a default message is planned; only has to be in the future.
DEFAULT_PLAN_OFFSET = timedelta(days=1)


def make_mailbox(session: Session, *, owner: User | None = None, **overrides: object) -> Mailbox:
    """Insert an active mailbox with a unique lowercase address (shared unless an owner is set)."""
    fields: dict[str, object] = {
        "address": f"mailbox{next_number()}@example.com",
        "owner_id": owner.id if owner else None,
    }
    return persist(session, Mailbox(**{**fields, **overrides}))


def make_outreach_message(
    session: Session,
    *,
    draft: EmailDraft | None = None,
    mailbox: Mailbox | None = None,
    **overrides: object,
) -> OutreachMessage:
    """Insert a planned queue row for the draft (a new draft chain and mailbox if none are given).

    The campaign and person come from the draft's own sequence and lead, and a new work
    address is created for that person, so the row is consistent.
    """
    draft = draft or make_email_draft(session)
    sequence = session.get(EmailSequence, draft.sequence_id)
    lead = session.get(CampaignLead, sequence.campaign_lead_id)
    person = session.get(Person, lead.person_id)
    fields: dict[str, object] = {
        "draft_id": draft.id,
        "campaign_id": lead.campaign_id,
        "person_id": person.id,
        "person_email_id": make_person_email(session, person=person).id,
        "mailbox_id": (mailbox or make_mailbox(session)).id,
        "planned_for": now() + DEFAULT_PLAN_OFFSET,
        "idempotency_key": f"idempotency-key-{next_number()}",
    }
    return persist(session, OutreachMessage(**{**fields, **overrides}))


def make_send_attempt(
    session: Session, *, message: OutreachMessage | None = None, **overrides: object
) -> SendAttempt:
    """Insert attempt number 1 of the message (a new message if none is given), no error."""
    fields: dict[str, object] = {
        "message_id": (message or make_outreach_message(session)).id,
        "attempt_number": 1,
    }
    return persist(session, SendAttempt(**{**fields, **overrides}))
