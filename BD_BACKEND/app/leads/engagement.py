"""Applies the engagement history a source file carries about a person (M2-B3, D-073).

Needed because Apollo exports remember contact from before this app existed: someone who
unsubscribed there must never be emailed here, a bounced address must not be used, and a
person who replied or was contacted recently must stay out of new campaigns. ingest_row
(M2-B4) builds an EngagementHistory from the row and calls apply_engagement once the person
and their emails are saved. Nothing here commits; the caller owns the transaction. Deciding
who is *eligible* stays with the later eligibility service: this module only records facts.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.models import OptOut, OptOutSource
from app.core.models import Setting
from app.leads.contracts import ImportContext
from app.leads.models import (
    LeadEvent,
    Person,
    PersonEmail,
    Touch,
    TouchDirection,
)

# Settings row holding the cooling-off length in days; the default applies when it is missing
# or not a positive whole number (D-073, D-083).
COOLING_OFF_SETTING_KEY = "campaigns.cooling_off_days"
DEFAULT_COOLING_OFF_DAYS = 90

OPT_OUT_REASON = "Marked do-not-contact in the source file"
SOURCE_REPLIED_EVENT = "source_replied"


@dataclass(frozen=True, slots=True)
class EngagementHistory:
    """What the source file says about earlier contact with one person.

    Attributes:
        do_not_contact: The source marks the person do-not-contact or unsubscribed.
        bounced: The source says an email to this person bounced.
        replied: The source says the person replied.
        replied_at: When they replied, if the file says; "now" is used when it does not.
        last_contacted_at: When the source last contacted them, if the file says.
    """

    do_not_contact: bool = False
    bounced: bool = False
    replied: bool = False
    replied_at: datetime | None = None
    last_contacted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EngagementResult:
    """What apply_engagement changed, for tests and for the caller's change summary.

    Attributes:
        opt_outs_created: New opt-outs written (addresses that already had one are skipped).
        emails_marked_invalid: Addresses newly marked invalid after a bounce.
        reply_recorded: True when a reply was newly recorded and the owner flagged.
        last_contacted_at: The person's last-contact time after the rules ran.
        cooling_off_until: When the person may enter a new campaign again, or None.
    """

    opt_outs_created: int
    emails_marked_invalid: int
    reply_recorded: bool
    last_contacted_at: datetime | None
    cooling_off_until: datetime | None


def read_cooling_off_days(db: Session) -> int:
    """Return the cooling-off length in days from Settings, or the default of 90.

    A stored value that is not a positive whole number is ignored rather than trusted, so a
    bad admin edit cannot switch cooling-off off by accident.
    """
    value = db.execute(
        select(Setting.value).where(Setting.key == COOLING_OFF_SETTING_KEY)
    ).scalar_one_or_none()
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return DEFAULT_COOLING_OFF_DAYS


def cooling_off_until(last_contacted_at: datetime | None, cooling_off_days: int) -> datetime | None:
    """Return when cooling-off ends after a contact, or None when there was no contact."""
    if last_contacted_at is None:
        return None
    return last_contacted_at + timedelta(days=cooling_off_days)


def _latest(first: datetime | None, second: datetime | None) -> datetime | None:
    """Return the later of two optional times."""
    if first is None or second is None:
        return first or second
    return max(first, second)


def _own_last_outbound(db: Session, person_id: uuid.UUID) -> datetime | None:
    """Return the time of the app's own latest outbound contact with the person, if any."""
    return db.execute(
        select(Touch.occurred_at)
        .where(Touch.person_id == person_id, Touch.direction == TouchDirection.OUTBOUND)
        .order_by(Touch.occurred_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _record_opt_outs(db: Session, emails: list[PersonEmail], ctx: ImportContext) -> int:
    """Opt out every address of the person that has no active opt-out yet; return the count."""
    created = 0
    for address in {email.normalized_address for email in emails}:
        already_opted_out = db.execute(
            select(OptOut.id).where(OptOut.email_normalized == address, OptOut.removed_at.is_(None))
        ).first()
        if already_opted_out:
            continue
        db.add(
            OptOut(
                email_normalized=address,
                source=OptOutSource.IMPORTED,
                reason=OPT_OUT_REASON,
                created_by=ctx.uploaded_by,
                created_at=ctx.now,
            )
        )
        created += 1
    db.flush()
    return created


def _mark_bounced(person: Person, emails: list[PersonEmail]) -> int:
    """Mark the person's main address invalid after a bounce; return how many were newly marked.

    The bounce in an export belongs to the address the source mailed, which is the primary
    one; with no primary the first address is used. The person is also flagged as bounced.
    """
    person.email_bounced = True
    if not emails:
        return 0
    target = next((email for email in emails if email.is_primary), emails[0])
    if target.is_invalid:
        return 0
    target.is_invalid = True
    return 1


def _record_reply(
    db: Session, person: Person, history: EngagementHistory, ctx: ImportContext
) -> bool:
    """Record a source reply and flag the owner through the lead timeline.

    The latest reply time wins. The timeline event is written only the first time, so a
    re-import of the same file does not flag the owner again. Returns True when it was new.
    """
    reply_time = history.replied_at or ctx.now
    is_new = person.replied_at is None
    person.replied_at = _latest(person.replied_at, reply_time)
    if is_new:
        db.add(
            LeadEvent(
                person_id=person.id,
                event_type=SOURCE_REPLIED_EVENT,
                detail={"owner_id": str(person.owner_id) if person.owner_id else None},
                actor_id=None,
                occurred_at=ctx.now,
            )
        )
    return is_new


def apply_engagement(
    db: Session, person: Person, history: EngagementHistory, ctx: ImportContext
) -> EngagementResult:
    """Apply the source's engagement history to a saved person (D-073).

    Rules:
        * do-not-contact: an OptOut for every address of the person; the data stays valid.
        * bounced: the main address is marked invalid and the person flagged as bounced.
        * replied: replied_at is set (latest wins) and a "source_replied" timeline event
          flags the owner; the person is excluded from new campaigns by the eligibility check.
        * contacted: last_contacted_at becomes the app's own latest send when there is one
          (own records win), otherwise the latest of the stored and source dates; cooling-off
          runs from it for ctx.cooling_off_days.

    Call after the person and their emails are saved. Never commits.

    Returns:
        What was changed, including when cooling-off ends.
    """
    emails = list(
        db.execute(select(PersonEmail).where(PersonEmail.person_id == person.id)).scalars()
    )
    opt_outs_created = _record_opt_outs(db, emails, ctx) if history.do_not_contact else 0
    emails_marked_invalid = _mark_bounced(person, emails) if history.bounced else 0
    reply_recorded = _record_reply(db, person, history, ctx) if history.replied else False

    own_contact = _own_last_outbound(db, person.id)
    person.last_contacted_at = own_contact or _latest(
        person.last_contacted_at, history.last_contacted_at
    )
    db.flush()
    return EngagementResult(
        opt_outs_created=opt_outs_created,
        emails_marked_invalid=emails_marked_invalid,
        reply_recorded=reply_recorded,
        last_contacted_at=person.last_contacted_at,
        cooling_off_until=cooling_off_until(person.last_contacted_at, ctx.cooling_off_days),
    )
