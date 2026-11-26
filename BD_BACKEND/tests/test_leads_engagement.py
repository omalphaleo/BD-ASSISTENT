"""Tests for the source engagement rules in app.leads.engagement (M2-B3, D-073).

Needed because ignoring a source's do-not-contact, bounce or reply would email people who must
not be emailed. One test per rule: opt-out, bounced, replied, cooling-off, own send records
winning over source dates, the 90-day default and its Settings override, and that re-applying
the same history changes nothing. Synthetic data; time is passed in, never read.
"""

import uuid
from datetime import UTC, datetime, timedelta

from factories.compliance import make_opt_out
from factories.core import make_user
from factories.leads import make_person, make_person_email, make_touch
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.models import OptOut, OptOutSource
from app.core.models import Setting
from app.leads.contracts import ImportContext, IngestSource
from app.leads.engagement import (
    COOLING_OFF_SETTING_KEY,
    DEFAULT_COOLING_OFF_DAYS,
    SOURCE_REPLIED_EVENT,
    EngagementHistory,
    apply_engagement,
    cooling_off_until,
    read_cooling_off_days,
)
from app.leads.models import LeadEvent

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def _ctx(uploaded_by: uuid.UUID | None = None, days: int = 90) -> ImportContext:
    """An import context with a fixed clock."""
    return ImportContext(
        import_file_id=uuid.uuid4(),
        uploaded_by=uploaded_by,
        now=NOW,
        cooling_off_days=days,
        source=IngestSource.IMPORT,
    )


def test_do_not_contact_opts_out_every_address(db_session: Session) -> None:
    """Do-not-contact writes an imported OptOut for each of the person's addresses."""
    uploader = make_user(db_session)
    person = make_person(db_session)
    make_person_email(db_session, person=person, normalized_address="a@acme.example")
    make_person_email(db_session, person=person, normalized_address="b@acme.example")

    result = apply_engagement(
        db_session, person, EngagementHistory(do_not_contact=True), _ctx(uploader.id)
    )

    assert result.opt_outs_created == 2
    rows = db_session.scalars(
        select(OptOut).where(OptOut.email_normalized.in_(["a@acme.example", "b@acme.example"]))
    ).all()
    assert {row.email_normalized for row in rows} == {"a@acme.example", "b@acme.example"}
    assert {row.source for row in rows} == {OptOutSource.IMPORTED}
    assert {row.created_by for row in rows} == {uploader.id}


def test_do_not_contact_skips_an_address_already_opted_out(db_session: Session) -> None:
    """An address with an active opt-out gets no second one."""
    person = make_person(db_session)
    make_person_email(db_session, person=person, normalized_address="a@acme.example")
    make_opt_out(db_session, email_normalized="a@acme.example")

    result = apply_engagement(db_session, person, EngagementHistory(do_not_contact=True), _ctx())

    assert result.opt_outs_created == 0


def test_no_do_not_contact_creates_no_opt_out(db_session: Session) -> None:
    """Without the flag no opt-out is written."""
    person = make_person(db_session)
    make_person_email(db_session, person=person, normalized_address="solo@acme.example")

    result = apply_engagement(db_session, person, EngagementHistory(), _ctx())

    assert result.opt_outs_created == 0
    assert (
        db_session.scalars(
            select(OptOut).where(OptOut.email_normalized == "solo@acme.example")
        ).all()
        == []
    )


def test_bounced_marks_the_primary_email_invalid(db_session: Session) -> None:
    """A bounce marks the primary address invalid, leaves the others, and flags the person."""
    person = make_person(db_session)
    primary = make_person_email(
        db_session, person=person, normalized_address="a@acme.example", is_primary=True
    )
    other = make_person_email(db_session, person=person, normalized_address="b@acme.example")

    result = apply_engagement(db_session, person, EngagementHistory(bounced=True), _ctx())

    assert result.emails_marked_invalid == 1
    assert primary.is_invalid
    assert not other.is_invalid
    assert person.email_bounced


def test_bounced_twice_marks_nothing_new(db_session: Session) -> None:
    """Re-applying a bounce counts no new invalid address."""
    person = make_person(db_session)
    make_person_email(db_session, person=person, is_primary=True)
    apply_engagement(db_session, person, EngagementHistory(bounced=True), _ctx())

    result = apply_engagement(db_session, person, EngagementHistory(bounced=True), _ctx())

    assert result.emails_marked_invalid == 0


def test_replied_sets_replied_at_and_flags_the_owner_once(db_session: Session) -> None:
    """A reply sets replied_at and writes one timeline event naming the owner; not twice."""
    owner = make_user(db_session)
    person = make_person(db_session, owner_id=owner.id)
    replied_at = NOW - timedelta(days=3)
    history = EngagementHistory(replied=True, replied_at=replied_at)

    first = apply_engagement(db_session, person, history, _ctx())
    second = apply_engagement(db_session, person, history, _ctx())

    assert first.reply_recorded
    assert not second.reply_recorded
    assert person.replied_at == replied_at
    events = db_session.scalars(
        select(LeadEvent).where(
            LeadEvent.person_id == person.id, LeadEvent.event_type == SOURCE_REPLIED_EVENT
        )
    ).all()
    assert len(events) == 1
    assert events[0].detail == {"owner_id": str(owner.id)}


def test_replied_without_a_date_uses_now(db_session: Session) -> None:
    """A reply with no date in the file is recorded at the import time."""
    person = make_person(db_session)

    apply_engagement(db_session, person, EngagementHistory(replied=True), _ctx())

    assert person.replied_at == NOW


def test_source_contact_date_starts_cooling_off(db_session: Session) -> None:
    """With no own send, the source date becomes last_contacted_at and cooling-off follows."""
    person = make_person(db_session)
    contacted = NOW - timedelta(days=10)

    result = apply_engagement(
        db_session, person, EngagementHistory(last_contacted_at=contacted), _ctx(days=90)
    )

    assert person.last_contacted_at == contacted
    assert result.cooling_off_until == contacted + timedelta(days=90)


def test_most_recent_source_date_wins(db_session: Session) -> None:
    """An older source date never replaces a newer stored one."""
    newer = NOW - timedelta(days=5)
    person = make_person(db_session, last_contacted_at=newer)

    apply_engagement(
        db_session,
        person,
        EngagementHistory(last_contacted_at=NOW - timedelta(days=50)),
        _ctx(),
    )

    assert person.last_contacted_at == newer


def test_own_send_record_wins_over_the_source_date(db_session: Session) -> None:
    """The app's own latest outbound touch beats a later date in the file."""
    person = make_person(db_session)
    own = NOW - timedelta(days=30)
    make_touch(db_session, person=person, occurred_at=own)

    apply_engagement(
        db_session,
        person,
        EngagementHistory(last_contacted_at=NOW - timedelta(days=1)),
        _ctx(),
    )

    assert person.last_contacted_at == own


def test_no_contact_means_no_cooling_off(db_session: Session) -> None:
    """A person never contacted has no last-contact time and no cooling-off end."""
    person = make_person(db_session)

    result = apply_engagement(db_session, person, EngagementHistory(), _ctx())

    assert result.last_contacted_at is None
    assert result.cooling_off_until is None


def test_cooling_off_until_helper() -> None:
    """The end is the contact time plus the configured days; None without a contact."""
    assert cooling_off_until(NOW, 30) == NOW + timedelta(days=30)
    assert cooling_off_until(None, 30) is None


def test_cooling_off_days_default_is_90(db_session: Session) -> None:
    """With no Settings row the default of 90 days applies."""
    assert read_cooling_off_days(db_session) == DEFAULT_COOLING_OFF_DAYS == 90


def test_cooling_off_days_read_from_settings(db_session: Session) -> None:
    """An admin value in Settings replaces the default."""
    db_session.add(Setting(key=COOLING_OFF_SETTING_KEY, value=45))
    db_session.flush()

    assert read_cooling_off_days(db_session) == 45


def test_cooling_off_days_ignores_a_bad_value(db_session: Session) -> None:
    """A zero, negative, boolean or text value falls back to the default."""
    setting = Setting(key=COOLING_OFF_SETTING_KEY, value=0)
    db_session.add(setting)
    db_session.flush()
    for bad in (0, -5, True, "ninety"):
        setting.value = bad
        db_session.flush()
        assert read_cooling_off_days(db_session) == 90
