"""SQLAlchemy models for the campaigns module: campaigns, selected leads, sequences, drafts, checks.

Needed so M4 can store a rep's campaign, the leads picked for it with their eligibility result
(D-067), the three-email sequence drafted for each lead (D-090), each draft's AI-written
sections and edit history (Q-CONTENT-11) and the outcome of the nine automatic checks
(Q-CONTENT-09). Migration 0010 creates the same schema (0011 later adds the mailbox foreign
key). Tables only in M1 task B7: no service
reads or writes them yet and nothing is seeded. Fixed-value columns are VARCHAR plus a named
CHECK (not native enums), like the other modules.
"""

import enum
import uuid
from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.content.models import EmailStructureStep
from app.core.model_helpers import TimestampMixin, enum_column, in_check, uuid_pk
from app.db import Base


class CampaignStatus(enum.StrEnum):
    """Lifecycle of a campaign. The value list is an [ASSUMPTION]: the docs name no values.

    Pausing needs an explicit resume and never resumes by itself (D-015).
    """

    DRAFT = "draft"  # created, leads chosen, nothing drafted yet
    GENERATING = "generating"  # sequences are being drafted (D-090)
    AWAITING_REVIEW = "awaiting_review"  # drafted, waiting for the rep's review
    APPROVED = "approved"  # every sequence decided; ready for M5 to plan messages
    RUNNING = "running"  # messages are being sent
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EligibilityResult(enum.StrEnum):
    """Whether a selected lead may be contacted, as decided when the campaign is created."""

    ELIGIBLE = "eligible"
    EXCLUDED = "excluded"


class SequenceStatus(enum.StrEnum):
    """State of one lead's three-email sequence in the review flow (ARCHITECTURE 6.1b)."""

    GENERATING = "generating"
    READY = "ready"
    NEEDS_ATTENTION = "needs_attention"  # validation failed twice (Q-CONTENT-09)
    APPROVED = "approved"
    REJECTED = "rejected"


class DraftValidationStatus(enum.StrEnum):
    """Overall check outcome of one draft; pending until the validators have run."""

    PENDING = "pending"
    PASSED = "passed"
    WARNING = "warning"  # goes to review with the warning shown
    FAILED = "failed"  # regenerated once, then needs attention


class ValidatorCheck(enum.StrEnum):
    """The nine automatic checks every draft passes before review (Q-CONTENT-09), in order."""

    REQUIRED_SECTIONS = "required_sections"  # 1: sections present, fixed parts unchanged
    LENGTH_LIMITS = "length_limits"  # 2: word limits, subject at most 60 characters
    NO_PLACEHOLDERS = "no_placeholders"  # 3: no leftover "{...}" or "[Company]"
    LEAD_IDENTITY = "lead_identity"  # 4: first name and company match the lead
    SUPPORTED_CLAIMS = "supported_claims"  # 5: numbers and case-study claims have a source
    OFFERINGS_AND_BANNED_PHRASES = "offerings_and_banned_phrases"  # 6
    NO_LINKS_OR_ATTACHMENTS = "no_links_or_attachments"  # 7: in AI-written parts
    FORMATTING = "formatting"  # 8: no ALL-CAPS words, at most one "!"
    OPT_OUT_AND_ELIGIBILITY = "opt_out_and_eligibility"  # 9: re-checked at validation time


class CheckStatus(enum.StrEnum):
    """Result of a single automatic check."""

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class Campaign(TimestampMixin, Base):
    """A rep's outreach campaign: its owner, mailbox, sequence timing and target date."""

    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Only the owner edits the campaign (permission matrix). RESTRICT: users are deactivated,
    # not deleted, so a campaign never silently loses its owner.
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_campaigns_owner_id_users"),
        nullable=False,
    )
    # The sending mailbox (the admin decides per campaign, default the rep's own, D-002, D-013).
    # SET NULL: the campaign survives if its mailbox row is removed. The foreign key was added
    # by migration 0011, when the mailboxes table (task B8) was created.
    mailbox_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mailboxes.id", ondelete="SET NULL", name="fk_campaigns_mailbox_id_mailboxes"),
        nullable=True,
    )
    # Snapshot of the sequence timing taken at creation (D-082: follow-ups on business days 3
    # and 7), so a later admin settings change never alters a running campaign.
    sequence_config: Mapped[object] = mapped_column(JSONB, nullable=False)
    # The rep's wanted end date; the completion estimate warns when it cannot be met (D-083).
    target_completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[CampaignStatus] = mapped_column(
        enum_column(CampaignStatus),
        nullable=False,
        default=CampaignStatus.DRAFT,
        server_default=text("'draft'"),
    )

    __table_args__ = (
        in_check("status", CampaignStatus, "ck_campaigns_status_valid"),
        Index("ix_campaigns_owner_id", "owner_id"),
        Index("ix_campaigns_mailbox_id", "mailbox_id"),
        Index("ix_campaigns_status", "status"),
    )


class CampaignLead(TimestampMixin, Base):
    """A lead selected for a campaign, with the eligibility result recorded at selection."""

    __tablename__ = "campaign_leads"

    id: Mapped[uuid.UUID] = uuid_pk()
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE", name="fk_campaign_leads_campaign_id"),
        nullable=False,
    )
    # CASCADE: erase-person removes the lead everywhere (D-099).
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE", name="fk_campaign_leads_person_id_people"),
        nullable=False,
    )
    eligibility_result: Mapped[EligibilityResult] = mapped_column(
        enum_column(EligibilityResult), nullable=False
    )
    # Machine-readable reason such as "opted_out" (D-065, D-066). A format check, not a value
    # list: the compliance eligibility service that defines the reasons is not built yet.
    exclusion_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        in_check("eligibility_result", EligibilityResult, "ck_campaign_leads_eligibility_valid"),
        CheckConstraint(
            "exclusion_reason IS NULL OR exclusion_reason ~ '^[a-z0-9_]+$'",
            name="ck_campaign_leads_exclusion_reason_format",
        ),
        # An excluded lead always says why; an eligible lead never has a reason.
        CheckConstraint(
            "(eligibility_result = 'excluded') = (exclusion_reason IS NOT NULL)",
            name="ck_campaign_leads_reason_matches_result",
        ),
        UniqueConstraint("campaign_id", "person_id", name="uq_campaign_leads_campaign_person"),
        Index("ix_campaign_leads_person_id", "person_id"),
    )


class EmailSequence(TimestampMixin, Base):
    """The three-email sequence drafted for one campaign lead, reviewed as one unit (D-090)."""

    __tablename__ = "email_sequences"

    id: Mapped[uuid.UUID] = uuid_pk()
    # At most one sequence per campaign lead.
    campaign_lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "campaign_leads.id", ondelete="CASCADE", name="fk_email_sequences_campaign_lead_id"
        ),
        nullable=False,
    )
    status: Mapped[SequenceStatus] = mapped_column(
        enum_column(SequenceStatus),
        nullable=False,
        default=SequenceStatus.GENERATING,
        server_default=text("'generating'"),
    )

    __table_args__ = (
        in_check("status", SequenceStatus, "ck_email_sequences_status_valid"),
        UniqueConstraint("campaign_lead_id", name="uq_email_sequences_campaign_lead_id"),
        Index("ix_email_sequences_status", "status"),
    )


class EmailDraft(TimestampMixin, Base):
    """One email of a sequence: the AI-written sections, the assembled text and the edits."""

    __tablename__ = "email_drafts"

    id: Mapped[uuid.UUID] = uuid_pk()
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_sequences.id", ondelete="CASCADE", name="fk_email_drafts_sequence_id"),
        nullable=False,
    )
    step: Mapped[EmailStructureStep] = mapped_column(
        enum_column(EmailStructureStep), nullable=False
    )
    # What the AI wrote per section, keyed by section name; reps edit only these (Q-CONTENT-11).
    ai_sections: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # The assembled email (fixed sections + AI sections); empty until drafted. The final HTML
    # with footer and unsubscribe link is built at send time (M5), not stored here.
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_status: Mapped[DraftValidationStatus] = mapped_column(
        enum_column(DraftValidationStatus),
        nullable=False,
        default=DraftValidationStatus.PENDING,
        server_default=text("'pending'"),
    )
    # List of the rep's edits (who, when, what changed); empty until the first edit.
    edit_history: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        in_check("step", EmailStructureStep, "ck_email_drafts_step_valid"),
        in_check("validation_status", DraftValidationStatus, "ck_email_drafts_validation_valid"),
        UniqueConstraint("sequence_id", "step", name="uq_email_drafts_sequence_id_step"),
    )


class ValidationResult(TimestampMixin, Base):
    """The outcome of one automatic check on one draft, shown in the review queue."""

    __tablename__ = "validation_results"

    id: Mapped[uuid.UUID] = uuid_pk()
    draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_drafts.id", ondelete="CASCADE", name="fk_validation_results_draft_id"),
        nullable=False,
    )
    check_id: Mapped[ValidatorCheck] = mapped_column(enum_column(ValidatorCheck), nullable=False)
    status: Mapped[CheckStatus] = mapped_column(enum_column(CheckStatus), nullable=False)
    # Human-readable explanation of a warning or failure; empty for a pass.
    message: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))

    __table_args__ = (
        in_check("check_id", ValidatorCheck, "ck_validation_results_check_id_valid"),
        in_check("status", CheckStatus, "ck_validation_results_status_valid"),
        # One current result per check; a re-check after an edit updates the row.
        UniqueConstraint("draft_id", "check_id", name="uq_validation_results_draft_id_check_id"),
    )
