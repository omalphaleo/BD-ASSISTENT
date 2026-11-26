"""Test factories for the campaigns tables: campaigns, selected leads, sequences, drafts, checks.

Needed so tests build a valid campaign chain in one line (M1 task B11). Each factory creates its
required parent rows when none is passed (a user, a person, a campaign, ...), accepts overrides
for any column, and gives every call unique defaults. All data is synthetic.
"""

from sqlalchemy.orm import Session

from app.campaigns.models import (
    Campaign,
    CampaignLead,
    CheckStatus,
    EligibilityResult,
    EmailDraft,
    EmailSequence,
    ValidationResult,
    ValidatorCheck,
)
from app.content.models import EmailStructureStep
from app.core.models import User
from app.leads.models import Person
from factories.common import next_number, persist
from factories.core import make_user
from factories.leads import make_person

# The D-082 default timing (follow-ups on business days 3 and 7) stored on every campaign.
DEFAULT_SEQUENCE_CONFIG = {"follow_up_1_business_day": 3, "follow_up_2_business_day": 7}


def make_campaign(session: Session, *, owner: User | None = None, **overrides: object) -> Campaign:
    """Insert a draft campaign owned by the given user (a new rep if none is given)."""
    fields: dict[str, object] = {
        "name": f"Campaign {next_number()}",
        "owner_id": (owner or make_user(session)).id,
        "sequence_config": dict(DEFAULT_SEQUENCE_CONFIG),
    }
    return persist(session, Campaign(**{**fields, **overrides}))


def make_campaign_lead(
    session: Session,
    *,
    campaign: Campaign | None = None,
    person: Person | None = None,
    **overrides: object,
) -> CampaignLead:
    """Insert an eligible lead for the campaign (new campaign and person if none are given)."""
    fields: dict[str, object] = {
        "campaign_id": (campaign or make_campaign(session)).id,
        "person_id": (person or make_person(session)).id,
        "eligibility_result": EligibilityResult.ELIGIBLE,
    }
    return persist(session, CampaignLead(**{**fields, **overrides}))


def make_email_sequence(
    session: Session, *, campaign_lead: CampaignLead | None = None, **overrides: object
) -> EmailSequence:
    """Insert a generating sequence for the campaign lead (a new lead if none is given)."""
    fields: dict[str, object] = {
        "campaign_lead_id": (campaign_lead or make_campaign_lead(session)).id
    }
    return persist(session, EmailSequence(**{**fields, **overrides}))


def make_email_draft(
    session: Session, *, sequence: EmailSequence | None = None, **overrides: object
) -> EmailDraft:
    """Insert the first-email draft of the sequence (a new sequence if none is given)."""
    fields: dict[str, object] = {
        "sequence_id": (sequence or make_email_sequence(session)).id,
        "step": EmailStructureStep.FIRST_EMAIL,
    }
    return persist(session, EmailDraft(**{**fields, **overrides}))


def make_validation_result(
    session: Session, *, draft: EmailDraft | None = None, **overrides: object
) -> ValidationResult:
    """Insert a passed length check for the draft (a new draft if none is given)."""
    fields: dict[str, object] = {
        "draft_id": (draft or make_email_draft(session)).id,
        "check_id": ValidatorCheck.LENGTH_LIMITS,
        "status": CheckStatus.PASSED,
    }
    return persist(session, ValidationResult(**{**fields, **overrides}))
