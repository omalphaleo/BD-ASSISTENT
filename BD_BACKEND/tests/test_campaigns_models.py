"""Tests for the campaign-related database tables.

Covers campaigns, campaign_leads, email_sequences,
email_drafts, and validation_results.


Needed because the schema enforces the campaign rules (one sequence per lead, one draft per step,
one result per check, excluded leads always carry a reason, cascades on erase-person D-099) until
the M4 services exist. Runs against real PostgreSQL through the shared db_session fixture; all
data is synthetic (M1 task B7).
"""

import uuid
from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.campaigns.models import (
    Campaign,
    CampaignLead,
    CampaignStatus,
    CheckStatus,
    DraftValidationStatus,
    EligibilityResult,
    EmailDraft,
    EmailSequence,
    SequenceStatus,
    ValidationResult,
    ValidatorCheck,
)
from app.content.models import EmailStructureStep
from app.core.models import User
from app.leads.models import Person

Rejected = Callable[[object, str], None]

# Stand-in for the D-082 default timing snapshot stored on every campaign.
SEQUENCE_CONFIG = {"follow_up_1_business_day": 3, "follow_up_2_business_day": 7}


def _campaign(db_session: Session, owner: User) -> Campaign:
    """Insert and return a synthetic campaign owned by the given user."""
    campaign = Campaign(name="Q1 outreach", owner_id=owner.id, sequence_config=SEQUENCE_CONFIG)
    db_session.add(campaign)
    db_session.flush()
    return campaign


def _campaign_lead(db_session: Session, campaign: Campaign, person: Person) -> CampaignLead:
    """Insert and return an eligible campaign lead."""
    lead = CampaignLead(
        campaign_id=campaign.id, person_id=person.id, eligibility_result=EligibilityResult.ELIGIBLE
    )
    db_session.add(lead)
    db_session.flush()
    return lead


def _sequence(db_session: Session, lead: CampaignLead) -> EmailSequence:
    """Insert and return a sequence for the campaign lead."""
    sequence = EmailSequence(campaign_lead_id=lead.id)
    db_session.add(sequence)
    db_session.flush()
    return sequence


def _draft(db_session: Session, sequence: EmailSequence, step: EmailStructureStep) -> EmailDraft:
    """Insert and return a draft for the given step."""
    draft = EmailDraft(sequence_id=sequence.id, step=step)
    db_session.add(draft)
    db_session.flush()
    return draft


# --- campaigns ---


def test_campaign_defaults(db_session: Session, user: User) -> None:
    """A new campaign is a draft with no mailbox, no target date and timestamps set."""
    campaign = _campaign(db_session, user)
    db_session.refresh(campaign)

    assert campaign.status == CampaignStatus.DRAFT
    assert campaign.mailbox_id is None
    assert campaign.target_completion_date is None
    assert campaign.sequence_config == SEQUENCE_CONFIG
    assert campaign.created_at is not None


def test_campaign_stores_target_date(db_session: Session, user: User) -> None:
    """The target completion date round-trips as a date."""
    campaign = Campaign(
        name="Dated",
        owner_id=user.id,
        sequence_config=SEQUENCE_CONFIG,
        target_completion_date=date(2026, 12, 18),
    )
    db_session.add(campaign)
    db_session.flush()
    db_session.refresh(campaign)

    assert campaign.target_completion_date == date(2026, 12, 18)


def test_campaign_requires_an_existing_owner(assert_rejected: Rejected) -> None:
    """A campaign whose owner does not exist violates the foreign key."""
    assert_rejected(
        Campaign(name="Orphan", owner_id=uuid.uuid4(), sequence_config=SEQUENCE_CONFIG),
        "fk_campaigns_owner_id_users",
    )


def test_campaign_status_must_be_known(user: User, assert_rejected: Rejected) -> None:
    """A status outside the allowed list is rejected."""
    assert_rejected(
        Campaign(name="Bad", owner_id=user.id, sequence_config=SEQUENCE_CONFIG, status="sending"),
        "ck_campaigns_status_valid",
    )


def test_deleting_an_owner_with_campaigns_is_blocked(db_session: Session, user: User) -> None:
    """RESTRICT: a user who owns a campaign cannot be deleted."""
    _campaign(db_session, user)

    with (
        pytest.raises(IntegrityError, match="fk_campaigns_owner_id_users"),
        db_session.begin_nested(),
    ):
        db_session.execute(delete(User).where(User.id == user.id))


# --- campaign_leads ---


def test_excluded_lead_keeps_its_reason(db_session: Session, user: User, person: Person) -> None:
    """An excluded campaign lead stores the exclusion reason."""
    campaign = _campaign(db_session, user)
    lead = CampaignLead(
        campaign_id=campaign.id,
        person_id=person.id,
        eligibility_result=EligibilityResult.EXCLUDED,
        exclusion_reason="opted_out",
    )
    db_session.add(lead)
    db_session.flush()

    assert lead.exclusion_reason == "opted_out"


def test_excluded_lead_without_reason_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """Excluded with no reason violates the reason-matches-result check."""
    campaign = _campaign(db_session, user)

    assert_rejected(
        CampaignLead(
            campaign_id=campaign.id,
            person_id=person.id,
            eligibility_result=EligibilityResult.EXCLUDED,
        ),
        "ck_campaign_leads_reason_matches_result",
    )


def test_eligible_lead_with_reason_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """Eligible with a reason violates the reason-matches-result check."""
    campaign = _campaign(db_session, user)

    assert_rejected(
        CampaignLead(
            campaign_id=campaign.id,
            person_id=person.id,
            eligibility_result=EligibilityResult.ELIGIBLE,
            exclusion_reason="opted_out",
        ),
        "ck_campaign_leads_reason_matches_result",
    )


def test_exclusion_reason_must_be_snake_case(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A reason with spaces or capitals is rejected by the format check."""
    campaign = _campaign(db_session, user)

    assert_rejected(
        CampaignLead(
            campaign_id=campaign.id,
            person_id=person.id,
            eligibility_result=EligibilityResult.EXCLUDED,
            exclusion_reason="Opted Out",
        ),
        "ck_campaign_leads_exclusion_reason_format",
    )


def test_same_person_twice_in_a_campaign_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """Selecting the same person twice for one campaign violates the unique pair."""
    campaign = _campaign(db_session, user)
    _campaign_lead(db_session, campaign, person)

    assert_rejected(
        CampaignLead(
            campaign_id=campaign.id,
            person_id=person.id,
            eligibility_result=EligibilityResult.ELIGIBLE,
        ),
        "uq_campaign_leads_campaign_person",
    )


def test_same_person_in_two_campaigns_is_allowed(
    db_session: Session, user: User, person: Person
) -> None:
    """The unique pair is per campaign: one person can be in different campaigns."""
    lead_a = _campaign_lead(db_session, _campaign(db_session, user), person)
    lead_b = _campaign_lead(db_session, _campaign(db_session, user), person)

    assert lead_a.id != lead_b.id


def test_erasing_a_person_removes_their_campaign_leads(
    db_session: Session, user: User, person: Person
) -> None:
    """Erase-person (D-099): deleting the person cascades to their campaign leads."""
    campaign = _campaign(db_session, user)
    _campaign_lead(db_session, campaign, person)

    db_session.execute(delete(Person).where(Person.id == person.id))

    assert db_session.scalar(select(func.count()).select_from(CampaignLead)) == 0


# --- email_sequences ---


def test_sequence_defaults_to_generating(db_session: Session, user: User, person: Person) -> None:
    """A new sequence starts in the generating state."""
    lead = _campaign_lead(db_session, _campaign(db_session, user), person)
    sequence = _sequence(db_session, lead)
    db_session.refresh(sequence)

    assert sequence.status == SequenceStatus.GENERATING


def test_second_sequence_for_a_lead_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A campaign lead has at most one sequence."""
    lead = _campaign_lead(db_session, _campaign(db_session, user), person)
    _sequence(db_session, lead)

    assert_rejected(EmailSequence(campaign_lead_id=lead.id), "uq_email_sequences_campaign_lead_id")


def test_sequence_status_must_be_known(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A sequence status outside the allowed list is rejected."""
    lead = _campaign_lead(db_session, _campaign(db_session, user), person)

    assert_rejected(
        EmailSequence(campaign_lead_id=lead.id, status="sent"), "ck_email_sequences_status_valid"
    )


# --- email_drafts ---


def test_draft_defaults(db_session: Session, user: User, person: Person) -> None:
    """A new draft has empty AI sections and edit history, no text and pending validation."""
    lead = _campaign_lead(db_session, _campaign(db_session, user), person)
    draft = _draft(db_session, _sequence(db_session, lead), EmailStructureStep.FIRST_EMAIL)
    db_session.refresh(draft)

    assert draft.ai_sections == {}
    assert draft.edit_history == []
    assert draft.subject is None
    assert draft.body is None
    assert draft.validation_status == DraftValidationStatus.PENDING


def test_draft_stores_ai_sections_as_json(db_session: Session, user: User, person: Person) -> None:
    """AI sections round-trip as a JSON object keyed by section name."""
    lead = _campaign_lead(db_session, _campaign(db_session, user), person)
    sequence = _sequence(db_session, lead)
    draft = EmailDraft(
        sequence_id=sequence.id,
        step=EmailStructureStep.FIRST_EMAIL,
        ai_sections={"opening": "Hello", "relevance": "Because"},
    )
    db_session.add(draft)
    db_session.flush()
    db_session.refresh(draft)

    assert draft.ai_sections["opening"] == "Hello"


def test_duplicate_step_in_a_sequence_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A sequence has one draft per step."""
    lead = _campaign_lead(db_session, _campaign(db_session, user), person)
    sequence = _sequence(db_session, lead)
    _draft(db_session, sequence, EmailStructureStep.FOLLOW_UP_1)

    assert_rejected(
        EmailDraft(sequence_id=sequence.id, step=EmailStructureStep.FOLLOW_UP_1),
        "uq_email_drafts_sequence_id_step",
    )


def test_a_sequence_holds_three_steps(db_session: Session, user: User, person: Person) -> None:
    """All three steps (first email, follow-up 1, follow-up 2) can coexist in one sequence."""
    lead = _campaign_lead(db_session, _campaign(db_session, user), person)
    sequence = _sequence(db_session, lead)
    for step in EmailStructureStep:
        _draft(db_session, sequence, step)

    count = db_session.scalar(
        select(func.count()).select_from(EmailDraft).where(EmailDraft.sequence_id == sequence.id)
    )
    assert count == 3


def test_draft_validation_status_must_be_known(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A draft validation status outside the allowed list is rejected."""
    lead = _campaign_lead(db_session, _campaign(db_session, user), person)
    sequence = _sequence(db_session, lead)

    assert_rejected(
        EmailDraft(
            sequence_id=sequence.id, step=EmailStructureStep.FIRST_EMAIL, validation_status="ok"
        ),
        "ck_email_drafts_validation_valid",
    )


# --- validation_results ---


def test_validation_result_defaults(db_session: Session, user: User, person: Person) -> None:
    """A result has an empty message by default and keeps its check and status."""
    lead = _campaign_lead(db_session, _campaign(db_session, user), person)
    draft = _draft(db_session, _sequence(db_session, lead), EmailStructureStep.FIRST_EMAIL)
    result = ValidationResult(
        draft_id=draft.id, check_id=ValidatorCheck.LENGTH_LIMITS, status=CheckStatus.PASSED
    )
    db_session.add(result)
    db_session.flush()
    db_session.refresh(result)

    assert result.message == ""
    assert result.check_id == ValidatorCheck.LENGTH_LIMITS


def test_same_check_twice_on_a_draft_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A draft has one current result per check."""
    lead = _campaign_lead(db_session, _campaign(db_session, user), person)
    draft = _draft(db_session, _sequence(db_session, lead), EmailStructureStep.FIRST_EMAIL)
    db_session.add(
        ValidationResult(
            draft_id=draft.id, check_id=ValidatorCheck.FORMATTING, status=CheckStatus.PASSED
        )
    )
    db_session.flush()

    assert_rejected(
        ValidationResult(
            draft_id=draft.id, check_id=ValidatorCheck.FORMATTING, status=CheckStatus.FAILED
        ),
        "uq_validation_results_draft_id_check_id",
    )


def test_unknown_check_is_rejected(
    db_session: Session, user: User, person: Person, assert_rejected: Rejected
) -> None:
    """A check id outside the nine validators is rejected."""
    lead = _campaign_lead(db_session, _campaign(db_session, user), person)
    draft = _draft(db_session, _sequence(db_session, lead), EmailStructureStep.FIRST_EMAIL)

    assert_rejected(
        ValidationResult(draft_id=draft.id, check_id="tenth_check", status=CheckStatus.PASSED),
        "ck_validation_results_check_id_valid",
    )


def test_deleting_a_campaign_cascades_to_everything_below(
    db_session: Session, user: User, person: Person
) -> None:
    """Deleting a campaign removes its leads, sequence, drafts and validation results."""
    campaign = _campaign(db_session, user)
    lead = _campaign_lead(db_session, campaign, person)
    draft = _draft(db_session, _sequence(db_session, lead), EmailStructureStep.FIRST_EMAIL)
    db_session.add(
        ValidationResult(
            draft_id=draft.id, check_id=ValidatorCheck.NO_PLACEHOLDERS, status=CheckStatus.PASSED
        )
    )
    db_session.flush()

    db_session.execute(delete(Campaign).where(Campaign.id == campaign.id))

    for model in (CampaignLead, EmailSequence, EmailDraft, ValidationResult):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0, model
