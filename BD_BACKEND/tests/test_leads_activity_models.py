"""Tests for Segment, LeadNote, LeadEvent, Touch, LeadStatusFlag and the two mapping tables.

Needed because enum CHECKs, per-person flag uniqueness, the RESTRICT/SET NULL rules on users
and the lowercase mapping keys are enforced by the database (M1 task A3). All data is
synthetic.
"""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.models import User
from app.leads.models import (
    IndustryMapping,
    LeadEvent,
    LeadNote,
    LeadStatusFlag,
    LeadStatusFlagType,
    Person,
    Segment,
    SegmentVisibility,
    StateMapping,
    Touch,
    TouchChannel,
    TouchDirection,
    TouchStatus,
)


def _touch(person: Person, **kwargs: object) -> Touch:
    """Build an outbound email touch for a person; keyword arguments override the defaults."""
    values: dict[str, object] = {
        "person_id": person.id,
        "channel": TouchChannel.EMAIL,
        "direction": TouchDirection.OUTBOUND,
        "status": TouchStatus.SENT,
    }
    values.update(kwargs)
    return Touch(**values)


def test_segment_defaults_to_private(db_session: Session, user: User) -> None:
    """A saved filter is private unless shared explicitly."""
    segment = Segment(name="US healthcare", filters={"industry": ["Healthcare"]}, owner_id=user.id)
    db_session.add(segment)
    db_session.flush()
    db_session.refresh(segment)

    assert segment.visibility is SegmentVisibility.PRIVATE


def test_segment_visibility_is_limited_to_known_values(db_session: Session) -> None:
    """An unknown visibility is rejected by the CHECK."""
    db_session.add(Segment(name="x", filters={}, visibility="team"))
    with pytest.raises(IntegrityError, match="ck_segments_visibility_valid"):
        db_session.flush()


def test_note_cannot_be_blank(db_session: Session, person: Person, user: User) -> None:
    """A whitespace-only note body is rejected."""
    db_session.add(LeadNote(person_id=person.id, author_id=user.id, body="   "))
    with pytest.raises(IntegrityError, match="ck_lead_notes_body_not_blank"):
        db_session.flush()


def test_a_user_with_notes_cannot_be_deleted(
    db_session: Session, person: Person, user: User
) -> None:
    """Deleting a note's author is blocked (RESTRICT): deactivate the user instead."""
    db_session.add(LeadNote(person_id=person.id, author_id=user.id, body="Called, no answer"))
    db_session.flush()

    with pytest.raises(IntegrityError, match="fk_lead_notes_author_id_users"):
        db_session.execute(delete(User).where(User.id == user.id))


def test_event_type_must_be_a_lowercase_code(db_session: Session, person: Person) -> None:
    """An event type with capitals or spaces ("Flag Set") is rejected by the format CHECK."""
    db_session.add(LeadEvent(person_id=person.id, event_type="Flag Set"))
    with pytest.raises(IntegrityError, match="ck_lead_events_event_type_format"):
        db_session.flush()


def test_event_accepts_later_link_columns_without_foreign_keys(
    db_session: Session, person: Person
) -> None:
    """campaign_id and outreach_message_id hold any UUID for now: B adds the FKs later."""
    event = LeadEvent(
        person_id=person.id,
        event_type="flag.set",
        campaign_id=uuid.uuid4(),
        outreach_message_id=uuid.uuid4(),
    )
    db_session.add(event)
    db_session.flush()  # must not raise


def test_touch_enums_are_limited_to_known_values(
    person: Person, assert_rejected: Callable[[object, str], None]
) -> None:
    """An unknown channel, direction or status is rejected by its CHECK."""
    for column, constraint in (
        ("channel", "ck_touches_channel_valid"),
        ("direction", "ck_touches_direction_valid"),
        ("status", "ck_touches_status_valid"),
    ):
        # "fax" is short enough for every column, so the CHECK (not the length) is what fails.
        assert_rejected(_touch(person, **{column: "fax"}), constraint)


def test_deleting_the_rep_keeps_the_touch(db_session: Session, person: Person, user: User) -> None:
    """Contact history survives deletion of the rep who made it (rep_id becomes NULL)."""
    touch = _touch(person, rep_id=user.id)
    db_session.add(touch)
    db_session.flush()

    db_session.execute(delete(User).where(User.id == user.id))
    db_session.refresh(touch)

    assert touch.rep_id is None


def test_a_flag_is_set_once_per_person(db_session: Session, person: Person, user: User) -> None:
    """The same flag cannot be set twice on a person, but different flags can coexist."""
    db_session.add_all(
        [
            LeadStatusFlag(
                person_id=person.id, flag_type=LeadStatusFlagType.QUALIFIED, set_by=user.id
            ),
            LeadStatusFlag(
                person_id=person.id, flag_type=LeadStatusFlagType.PARTNER, set_by=user.id
            ),
        ]
    )
    db_session.flush()

    db_session.add(LeadStatusFlag(person_id=person.id, flag_type=LeadStatusFlagType.QUALIFIED))
    with pytest.raises(IntegrityError, match="uq_lead_status_flags_person_id_flag_type"):
        db_session.flush()


def test_flag_type_is_limited_to_known_values(db_session: Session, person: Person) -> None:
    """An unknown flag type is rejected by the CHECK."""
    db_session.add(LeadStatusFlag(person_id=person.id, flag_type="vip"))
    with pytest.raises(IntegrityError, match="ck_lead_status_flags_flag_type_valid"):
        db_session.flush()


def test_mapping_keys_must_be_lowercase(assert_rejected: Callable[[object, str], None]) -> None:
    """Industry and state mapping source text must be stored lowercase."""
    assert_rejected(
        IndustryMapping(source_name="Hospital & Health Care", standard_industry="Healthcare"),
        "ck_industry_mappings_source_lowercase",
    )
    assert_rejected(
        StateMapping(country="United States", source_value="CA", standard_name="California"),
        "ck_state_mappings_source_lowercase",
    )


def test_mapping_keys_are_unique(
    db_session: Session, assert_rejected: Callable[[object, str], None]
) -> None:
    """A source name (or country + source value) maps to only one standard value."""
    db_session.add_all(
        [
            IndustryMapping(source_name="software", standard_industry="Information"),
            StateMapping(country="United States", source_value="ca", standard_name="California"),
        ]
    )
    db_session.flush()

    assert_rejected(
        IndustryMapping(source_name="software", standard_industry="Other"),
        "uq_industry_mappings_source_name",
    )
    assert_rejected(
        StateMapping(country="United States", source_value="ca", standard_name="Cali"),
        "uq_state_mappings_country_source",
    )
