"""Test factory for search and eligibility tests (M3-A1, W1).

Needed so tests build a lead that is eligible by default in one line and then break exactly one
rule at a time. It builds on the shared leads and compliance factories (read-only use) and adds
nothing to the database schema. All data is synthetic.
"""

from sqlalchemy.orm import Session

from app.core.models import User
from app.leads.models import Person, Segment, SegmentVisibility
from factories.leads import make_person, make_person_email, make_segment


def make_eligible_person(session: Session, **person_overrides: object) -> Person:
    """Insert a person with one valid, verified work address and no other facts.

    Such a person passes every eligibility rule, so a test changes one fact and checks the
    reason that appears.
    """
    person = make_person(session, **person_overrides)
    make_person_email(session, person=person, verification_status="verified", is_primary=True)
    return person


def make_owned_segment(
    session: Session,
    owner: User | None,
    *,
    shared: bool = False,
    **overrides: object,
) -> Segment:
    """Insert a segment for the owner (None = ownerless), private unless `shared` is true."""
    visibility = SegmentVisibility.SHARED if shared else SegmentVisibility.PRIVATE
    return make_segment(
        session,
        owner_id=owner.id if owner else None,
        visibility=visibility,
        **overrides,
    )
