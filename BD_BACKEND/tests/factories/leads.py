"""Test factories for the leads tables: companies, people and everything attached to them.

Needed so tests (and B's factories, which need people for foreign keys) build valid synthetic
leads in one line. Each factory creates its required parent rows when none is passed, and
accepts overrides for any column. All data is synthetic.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.models import User
from app.leads.models import (
    Company,
    ContactChannel,
    ContactChannelType,
    DuplicateCandidate,
    EmailType,
    IndustryMapping,
    LeadEvent,
    LeadNote,
    LeadStatusFlag,
    LeadStatusFlagType,
    MergeRecord,
    Person,
    PersonEmail,
    PersonPhone,
    QuarantineRecord,
    Segment,
    SocialProfile,
    StateMapping,
    Touch,
    TouchChannel,
    TouchDirection,
    TouchStatus,
)
from factories.common import next_number, persist
from factories.core import make_user


def make_company(session: Session, **overrides: object) -> Company:
    """Insert a company with a unique name and lower-case domain."""
    number = next_number()
    fields: dict[str, object] = {
        "name": f"Acme Test Co {number}",
        "normalized_name": f"acme test co {number}",
        "domain": f"acme{number}.example",
    }
    return persist(session, Company(**{**fields, **overrides}))


def make_person(session: Session, **overrides: object) -> Person:
    """Insert a person with no company and no owner unless overrides say otherwise."""
    fields: dict[str, object] = {"first_name": f"Jane{next_number()}", "last_name": "Doe"}
    return persist(session, Person(**{**fields, **overrides}))


def make_person_email(
    session: Session, *, person: Person | None = None, **overrides: object
) -> PersonEmail:
    """Insert a work email (not primary, unverified by default) for the person."""
    number = next_number()
    address = f"jane{number}@acme.example"
    fields: dict[str, object] = {
        "person_id": (person or make_person(session)).id,
        "address": address,
        "normalized_address": address,
        "type": EmailType.WORK,
    }
    return persist(session, PersonEmail(**{**fields, **overrides}))


def make_person_phone(
    session: Session, *, person: Person | None = None, **overrides: object
) -> PersonPhone:
    """Insert a phone number with a unique value for the person."""
    fields: dict[str, object] = {
        "person_id": (person or make_person(session)).id,
        "number": f"+1555{next_number():07d}",
    }
    return persist(session, PersonPhone(**{**fields, **overrides}))


def make_social_profile(
    session: Session, *, person: Person | None = None, **overrides: object
) -> SocialProfile:
    """Insert a LinkedIn profile with a unique URL for the person."""
    fields: dict[str, object] = {
        "person_id": (person or make_person(session)).id,
        "network": "linkedin",
        "url": f"https://linkedin.example/in/jane{next_number()}",
    }
    return persist(session, SocialProfile(**{**fields, **overrides}))


def make_contact_channel(
    session: Session, *, company: Company | None = None, **overrides: object
) -> ContactChannel:
    """Insert a generic info@ email channel for the company."""
    fields: dict[str, object] = {
        "company_id": (company or make_company(session)).id,
        "channel_type": ContactChannelType.EMAIL,
        "value": f"info{next_number()}@acme.example",
    }
    return persist(session, ContactChannel(**{**fields, **overrides}))


def make_quarantine_record(session: Session, **overrides: object) -> QuarantineRecord:
    """Insert an open quarantine record (no raw row linked) with an empty payload."""
    fields: dict[str, object] = {"issues": ["personal_email_only"], "payload": {}}
    return persist(session, QuarantineRecord(**{**fields, **overrides}))


def make_duplicate_candidate(session: Session, **overrides: object) -> DuplicateCandidate:
    """Insert an open duplicate pair of two new people, stored with person_a_id < person_b_id.

    The table requires that ordering (so (A, B) and (B, A) cannot both exist), so the two
    people are sorted by id before the row is built.
    """
    first, second = sorted((make_person(session), make_person(session)), key=lambda p: p.id)
    fields: dict[str, object] = {
        "person_a_id": first.id,
        "person_b_id": second.id,
        "reason": "name_and_company_domain",
    }
    return persist(session, DuplicateCandidate(**{**fields, **overrides}))


def make_merge_record(
    session: Session, *, survivor: Person | None = None, **overrides: object
) -> MergeRecord:
    """Insert a merge record for a surviving person; the absorbed person id is a random UUID.

    The absorbed person row no longer exists after a real merge, so it has no foreign key.
    """
    fields: dict[str, object] = {
        "survivor_id": (survivor or make_person(session)).id,
        "absorbed_person_id": uuid.uuid4(),
        "snapshot": {},
    }
    return persist(session, MergeRecord(**{**fields, **overrides}))


def make_segment(session: Session, **overrides: object) -> Segment:
    """Insert a private segment with a unique name and an empty filter set."""
    fields: dict[str, object] = {"name": f"Segment {next_number()}", "filters": {}}
    return persist(session, Segment(**{**fields, **overrides}))


def make_lead_note(
    session: Session,
    *,
    person: Person | None = None,
    author: User | None = None,
    **overrides: object,
) -> LeadNote:
    """Insert a note on the person written by the author (new rows are made when omitted)."""
    fields: dict[str, object] = {
        "person_id": (person or make_person(session)).id,
        "author_id": (author or make_user(session)).id,
        "body": "Synthetic note.",
    }
    return persist(session, LeadNote(**{**fields, **overrides}))


def make_lead_event(
    session: Session, *, person: Person | None = None, **overrides: object
) -> LeadEvent:
    """Insert a timeline event ("test.event") for the person."""
    fields: dict[str, object] = {
        "person_id": (person or make_person(session)).id,
        "event_type": "test.event",
    }
    return persist(session, LeadEvent(**{**fields, **overrides}))


def make_touch(session: Session, *, person: Person | None = None, **overrides: object) -> Touch:
    """Insert an outbound email touch with status "sent" for the person."""
    fields: dict[str, object] = {
        "person_id": (person or make_person(session)).id,
        "channel": TouchChannel.EMAIL,
        "direction": TouchDirection.OUTBOUND,
        "status": TouchStatus.SENT,
    }
    return persist(session, Touch(**{**fields, **overrides}))


def make_lead_status_flag(
    session: Session, *, person: Person | None = None, **overrides: object
) -> LeadStatusFlag:
    """Insert a "qualified" flag on the person."""
    fields: dict[str, object] = {
        "person_id": (person or make_person(session)).id,
        "flag_type": LeadStatusFlagType.QUALIFIED,
    }
    return persist(session, LeadStatusFlag(**{**fields, **overrides}))


def make_industry_mapping(session: Session, **overrides: object) -> IndustryMapping:
    """Insert an industry mapping with a unique lower-case source name."""
    fields: dict[str, object] = {
        "source_name": f"software {next_number()}",
        "standard_industry": "Information Technology",
    }
    return persist(session, IndustryMapping(**{**fields, **overrides}))


def make_state_mapping(session: Session, **overrides: object) -> StateMapping:
    """Insert a state mapping with a unique lower-case source value."""
    fields: dict[str, object] = {
        "country": "United States",
        "source_value": f"calif {next_number()}",
        "standard_name": "California",
    }
    return persist(session, StateMapping(**{**fields, **overrides}))
