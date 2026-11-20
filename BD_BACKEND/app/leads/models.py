"""SQLAlchemy models for the leads module: companies, people and everything attached to them.

Needed as the unified lead layer: M2 import writes and merges these rows, and M3 search, lead
detail and status flags read them. Unified data keeps the latest values only, with no change
history (D-008); the immutable raw import rows live in the imports module (M1 task A4).
Migration 0006 creates the same schema; the foreign keys that point at tables built later
(campaigns, outreach messages) are added by those later migrations, not here. The one to
raw_rows (quarantine_records.raw_row_id) was added by migration 0007 (M1 task A4).
Fixed-value columns are VARCHAR plus a named CHECK (not native enums) so the lists can grow.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import now
from app.core.model_helpers import TimestampMixin, enum_column, in_check, uuid_pk
from app.db import Base

# --- Fixed-value sets. Each is stored as lowercase VARCHAR guarded by a named CHECK. ---


class EmailType(enum.StrEnum):
    """Kind of address: only 'work' addresses are used for outreach (D-072)."""

    WORK = "work"
    PERSONAL = "personal"
    GENERIC = "generic"


class EmailVerificationStatus(enum.StrEnum):
    """Source verification state; unverified addresses stay eligible with a warning (D-042)."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class ContactChannelType(enum.StrEnum):
    """Kind of company-level channel (such as info@ or a main phone line)."""

    EMAIL = "email"
    PHONE = "phone"


class QuarantineStatus(enum.StrEnum):
    """Lifecycle of a quarantined import row (D-068, D-107)."""

    OPEN = "open"
    RELEASED = "released"
    DISCARDED = "discarded"


class DuplicateStatus(enum.StrEnum):
    """Review state of a flagged duplicate pair (D-092)."""

    OPEN = "open"
    MERGED = "merged"
    NOT_DUPLICATE = "not_duplicate"


class SegmentVisibility(enum.StrEnum):
    """Whether a saved filter is visible only to its owner or to every BD user (D-009)."""

    PRIVATE = "private"
    SHARED = "shared"


class LeadStatusFlagType(enum.StrEnum):
    """Business flags set by BD users (D-022, D-065, D-101)."""

    EXISTING_CUSTOMER = "existing_customer"
    IN_CONVERSATION = "in_conversation"
    PARTNER = "partner"
    COMPETITOR = "competitor"
    QUALIFIED = "qualified"
    HANDED_OFF_TO_SALES = "handed_off_to_sales"


class TouchChannel(enum.StrEnum):
    """Channel of a contact; only email ships in v1 (D-034), more are added by a CHECK change."""

    EMAIL = "email"


class TouchDirection(enum.StrEnum):
    """Whether the app's user contacted the lead or the lead contacted the app's user."""

    OUTBOUND = "outbound"
    INBOUND = "inbound"


class TouchStatus(enum.StrEnum):
    """Engagement outcome recorded on a touch (D-063)."""

    SENT = "sent"
    OPENED = "opened"
    BOUNCED = "bounced"
    REPLIED = "replied"
    DEMOED = "demoed"


# --- Companies and people ---


class Company(TimestampMixin, Base):
    """A target company, with the latest known values only (D-008, D-063, D-089)."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Matching keys, in D-077 order: Apollo Account Id, then domain, then normalized name.
    apollo_account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # True when the name was derived from the work-email domain (D-071).
    name_is_derived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Standardized industry; a missing one is stored as "Unknown", never quarantined (D-070).
    industry: Mapped[str] = mapped_column(
        String(255), nullable=False, default="Unknown", server_default=text("'Unknown'")
    )
    naics: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sic: Mapped[str | None] = mapped_column(String(16), nullable=True)
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Currency is not recorded: the source does not state one (revenue and funding as given).
    annual_revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    funding_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latest_funding_round_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_funding: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    latest_funding_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Lowercased, trimmed values; GIN-indexed for exact "contains" filters (M3).
    technologies: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    keywords: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    # Derived from technologies; the leads service recomputes it on every technologies change.
    uses_salesforce: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    hq_city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    hq_state: Mapped[str | None] = mapped_column(String(128), nullable=True)
    hq_country: Mapped[str | None] = mapped_column(String(128), nullable=True)
    founded_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("apollo_account_id", name="uq_companies_apollo_account_id"),
        CheckConstraint("domain = lower(domain)", name="ck_companies_domain_lowercase"),
        CheckConstraint("employee_count >= 0", name="ck_companies_employee_count_nonnegative"),
        CheckConstraint("annual_revenue >= 0", name="ck_companies_annual_revenue_nonnegative"),
        CheckConstraint("total_funding >= 0", name="ck_companies_total_funding_nonnegative"),
        Index("ix_companies_domain", "domain"),
        Index("ix_companies_normalized_name", "normalized_name"),
        Index("ix_companies_industry", "industry"),
        Index("ix_companies_hq_country_hq_state", "hq_country", "hq_state"),
        Index("ix_companies_technologies", "technologies", postgresql_using="gin"),
        Index("ix_companies_keywords", "keywords", postgresql_using="gin"),
    )


class Person(TimestampMixin, Base):
    """A lead, with the latest known values only (D-008, D-063).

    "Possible duplicate" is not stored here: it is derived from open duplicate_candidates
    rows (D-092). Rows are removed only by merge or by erase-person (D-099), so there is no
    soft-delete column.
    """

    __tablename__ = "people"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Matching keys, in D-077 order. Not unique: uncertain matches are imported as separate
    # records until a manager merges them (D-092).
    source_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # First name is one of the two mandatory fields (D-069).
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(64), nullable=True)
    department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str | None] = mapped_column(String(128), nullable=True)
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # IANA zone name; the rep's zone is used when it is missing (D-014, D-078).
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # NULL means the "Unassigned" pool for a manager to assign (D-075). SET NULL keeps the
    # lead when its owner is deleted.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_people_owner_id_users"),
        nullable=True,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL", name="fk_people_company_id_companies"),
        nullable=True,
    )
    # Source status and stage exactly as imported, free text: the app's own lead states are
    # not agreed yet and stay derived from touches, flags and opt-outs (D-064, D-074).
    source_status: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_stage: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Source lists, kept as tags (D-074).
    lists: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    last_contacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    email_bounced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Stored but unused in the MVP (D-074).
    intent_signals: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    qualify_contact: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    __table_args__ = (
        Index("ix_people_source_record_id", "source_record_id"),
        Index("ix_people_linkedin_url", "linkedin_url"),
        Index("ix_people_company_id", "company_id"),
        Index("ix_people_owner_id", "owner_id"),
        Index("ix_people_seniority", "seniority"),
        Index("ix_people_country_state", "country", "state"),
    )


class PersonEmail(TimestampMixin, Base):
    """One email address of a person; people can have several, verified differently."""

    __tablename__ = "person_emails"

    id: Mapped[uuid.UUID] = uuid_pk()
    # CASCADE: erase-person removes the person's addresses (D-099).
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE", name="fk_person_emails_person_id_people"),
        nullable=False,
    )
    # As received, for display.
    address: Mapped[str] = mapped_column(String(320), nullable=False)
    # Lowercased, trimmed form used for matching and opt-out lookups (D-066, D-077).
    normalized_address: Mapped[str] = mapped_column(String(320), nullable=False)
    type: Mapped[EmailType] = mapped_column(enum_column(EmailType), nullable=False)
    verification_status: Mapped[EmailVerificationStatus] = mapped_column(
        enum_column(EmailVerificationStatus),
        nullable=False,
        default=EmailVerificationStatus.UNVERIFIED,
        server_default=text("'unverified'"),
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Set when the address bounced (D-073); the address is then never used.
    is_invalid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    __table_args__ = (
        # Not globally unique on purpose: possible-duplicate records can share an address
        # until merged (D-092); the matching service keeps clean people apart.
        UniqueConstraint(
            "person_id", "normalized_address", name="uq_person_emails_person_id_normalized"
        ),
        in_check("type", EmailType, "ck_person_emails_type_valid"),
        in_check(
            "verification_status",
            EmailVerificationStatus,
            "ck_person_emails_verification_status_valid",
        ),
        CheckConstraint(
            "normalized_address = lower(normalized_address)",
            name="ck_person_emails_normalized_lowercase",
        ),
        # At most one primary address per person.
        Index(
            "uq_person_emails_primary_per_person",
            "person_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        # Matching and opt-out lookups by address.
        Index("ix_person_emails_normalized_address", "normalized_address"),
    )


class PersonPhone(TimestampMixin, Base):
    """A phone number of a person; the type is the source's own label."""

    __tablename__ = "person_phones"

    id: Mapped[uuid.UUID] = uuid_pk()
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE", name="fk_person_phones_person_id_people"),
        nullable=False,
    )
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    # Free text (mobile, work, ...): the source's label list is not agreed.
    type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        UniqueConstraint("person_id", "number", name="uq_person_phones_person_id_number"),
    )


class SocialProfile(TimestampMixin, Base):
    """A social profile URL of a person (LinkedIn and others)."""

    __tablename__ = "social_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE", name="fk_social_profiles_person_id_people"),
        nullable=False,
    )
    # Free text, lowercase by convention (linkedin, twitter, ...).
    network: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)

    __table_args__ = (UniqueConstraint("person_id", "url", name="uq_social_profiles_person_url"),)


class ContactChannel(TimestampMixin, Base):
    """A generic company channel such as info@ that is not a named person's address."""

    __tablename__ = "contact_channels"

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "companies.id", ondelete="CASCADE", name="fk_contact_channels_company_id_companies"
        ),
        nullable=False,
    )
    channel_type: Mapped[ContactChannelType] = mapped_column(
        enum_column(ContactChannelType), nullable=False
    )
    value: Mapped[str] = mapped_column(String(320), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "company_id", "channel_type", "value", name="uq_contact_channels_company_type_value"
        ),
        in_check("channel_type", ContactChannelType, "ck_contact_channels_channel_type_valid"),
    )


# --- Import review: quarantine and duplicates ---


class QuarantineRecord(TimestampMixin, Base):
    """An import row held for a human to fix, release or discard (D-068, D-072, D-107).

    raw_row_id links to the untouched original in raw_rows (added by migration 0007, M1 task
    A4); it is nullable because a record can be created without one, and unique so each raw
    row has at most one quarantine record.
    """

    __tablename__ = "quarantine_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Reason codes found on the row, e.g. ["personal_email_only"].
    issues: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    status: Mapped[QuarantineStatus] = mapped_column(
        enum_column(QuarantineStatus),
        nullable=False,
        default=QuarantineStatus.OPEN,
        server_default=text("'open'"),
    )
    # The row's values as BD edits them; the original stays untouched in raw_rows (D-099).
    payload: Mapped[object] = mapped_column(JSONB, nullable=False)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_quarantine_records_resolved_by_users"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # CASCADE: erase-person deletes raw rows (D-099), and the record's payload holds the same
    # personal data, so it must go with them.
    raw_row_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "raw_rows.id", ondelete="CASCADE", name="fk_quarantine_records_raw_row_id_raw_rows"
        ),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("raw_row_id", name="uq_quarantine_records_raw_row_id"),
        in_check("status", QuarantineStatus, "ck_quarantine_records_status_valid"),
        # A record is resolved exactly when it has left the open state.
        CheckConstraint(
            "(status = 'open') = (resolved_at IS NULL)",
            name="ck_quarantine_records_resolved_at_matches_status",
        ),
        Index("ix_quarantine_records_status", "status"),
    )


class DuplicateCandidate(TimestampMixin, Base):
    """A pair of people flagged as a possible duplicate, awaiting a manager's decision (D-092).

    The pair is stored once with person_a_id < person_b_id so (A, B) and (B, A) cannot both
    exist.
    """

    __tablename__ = "duplicate_candidates"

    id: Mapped[uuid.UUID] = uuid_pk()
    person_a_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "people.id", ondelete="CASCADE", name="fk_duplicate_candidates_person_a_id_people"
        ),
        nullable=False,
    )
    person_b_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "people.id", ondelete="CASCADE", name="fk_duplicate_candidates_person_b_id_people"
        ),
        nullable=False,
    )
    # Which matching rule raised the pair, e.g. "name_and_company_domain".
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[DuplicateStatus] = mapped_column(
        enum_column(DuplicateStatus),
        nullable=False,
        default=DuplicateStatus.OPEN,
        server_default=text("'open'"),
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "users.id", ondelete="SET NULL", name="fk_duplicate_candidates_decided_by_users"
        ),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "person_a_id", "person_b_id", name="uq_duplicate_candidates_person_a_id_person_b_id"
        ),
        CheckConstraint("person_a_id < person_b_id", name="ck_duplicate_candidates_pair_ordered"),
        in_check("status", DuplicateStatus, "ck_duplicate_candidates_status_valid"),
        CheckConstraint(
            "(status = 'open') = (decided_at IS NULL)",
            name="ck_duplicate_candidates_decided_at_matches_status",
        ),
        Index("ix_duplicate_candidates_person_b_id", "person_b_id"),
        Index("ix_duplicate_candidates_status", "status"),
    )


class MergeRecord(Base):
    """History of one merge: the surviving person and a snapshot of the absorbed record (D-108).

    absorbed_person_id has no foreign key because the absorbed person row is deleted by the
    merge; the snapshot is what remains of it.
    """

    __tablename__ = "merge_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    # CASCADE: erasing the survivor also removes the snapshot, which holds personal data.
    survivor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE", name="fk_merge_records_survivor_id_people"),
        nullable=False,
    )
    absorbed_person_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    snapshot: Mapped[object] = mapped_column(JSONB, nullable=False)
    merged_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_merge_records_merged_by_users"),
        nullable=True,
    )
    merged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )

    __table_args__ = (Index("ix_merge_records_survivor_id", "survivor_id"),)


# --- Saved filters, notes, timeline, contact history, flags ---


class Segment(TimestampMixin, Base):
    """A named, saved filter combination, private to its owner or shared (D-009)."""

    __tablename__ = "segments"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # The filter set the search module builds queries from; never raw SQL.
    filters: Mapped[object] = mapped_column(JSONB, nullable=False)
    visibility: Mapped[SegmentVisibility] = mapped_column(
        enum_column(SegmentVisibility),
        nullable=False,
        default=SegmentVisibility.PRIVATE,
        server_default=text("'private'"),
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_segments_owner_id_users"),
        nullable=True,
    )

    __table_args__ = (
        in_check("visibility", SegmentVisibility, "ck_segments_visibility_valid"),
        Index("ix_segments_owner_id", "owner_id"),
    )


class LeadNote(TimestampMixin, Base):
    """A colleague's note about a lead (activity notes visible to every rep)."""

    __tablename__ = "lead_notes"

    id: Mapped[uuid.UUID] = uuid_pk()
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE", name="fk_lead_notes_person_id_people"),
        nullable=False,
    )
    # RESTRICT: a user who wrote notes cannot be deleted (deactivate instead).
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_lead_notes_author_id_users"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("btrim(body) <> ''", name="ck_lead_notes_body_not_blank"),
        Index("ix_lead_notes_person_id", "person_id"),
    )


class LeadEvent(Base):
    """One entry in a lead's timeline (imported, merged, flagged, contacted, ...)."""

    __tablename__ = "lead_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE", name="fk_lead_events_person_id_people"),
        nullable=False,
    )
    # Free-form code such as "flag.set"; the set of events grows with each module.
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_lead_events_actor_id_users"),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )
    # Links to tables built later (campaigns M1 B, outreach messages M1 B); those migrations
    # add the foreign keys, so these are plain UUIDs here.
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    outreach_message_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint("event_type ~ '^[a-z0-9_.]+$'", name="ck_lead_events_event_type_format"),
        Index("ix_lead_events_person_id_occurred_at", "person_id", "occurred_at"),
    )


class Touch(Base):
    """One contact with a lead on any channel: the shared contact history (D-026, D-034)."""

    __tablename__ = "touches"

    id: Mapped[uuid.UUID] = uuid_pk()
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE", name="fk_touches_person_id_people"),
        nullable=False,
    )
    channel: Mapped[TouchChannel] = mapped_column(enum_column(TouchChannel), nullable=False)
    direction: Mapped[TouchDirection] = mapped_column(enum_column(TouchDirection), nullable=False)
    # The rep who made the contact; SET NULL keeps the history if the user is deleted.
    rep_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_touches_rep_id_users"),
        nullable=True,
    )
    status: Mapped[TouchStatus] = mapped_column(enum_column(TouchStatus), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )
    # Same later-FK pattern as lead_events: B's migrations add these foreign keys.
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    outreach_message_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    __table_args__ = (
        in_check("channel", TouchChannel, "ck_touches_channel_valid"),
        in_check("direction", TouchDirection, "ck_touches_direction_valid"),
        in_check("status", TouchStatus, "ck_touches_status_valid"),
        Index("ix_touches_person_id_occurred_at", "person_id", "occurred_at"),
    )


class LeadStatusFlag(Base):
    """A business flag currently set on a person; clearing it deletes the row (D-008).

    Who set it and when is kept here; each change is also recorded in the audit log and
    the lead timeline (D-101), so no set/clear history is stored in this table.
    """

    __tablename__ = "lead_status_flags"

    id: Mapped[uuid.UUID] = uuid_pk()
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE", name="fk_lead_status_flags_person_id_people"),
        nullable=False,
    )
    flag_type: Mapped[LeadStatusFlagType] = mapped_column(
        enum_column(LeadStatusFlagType), nullable=False
    )
    set_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_lead_status_flags_set_by_users"),
        nullable=True,
    )
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)

    __table_args__ = (
        UniqueConstraint("person_id", "flag_type", name="uq_lead_status_flags_person_id_flag_type"),
        in_check("flag_type", LeadStatusFlagType, "ck_lead_status_flags_flag_type_valid"),
        Index("ix_lead_status_flags_flag_type", "flag_type"),
    )


# --- Lookup tables (empty until M2 seeds them) ---


class IndustryMapping(TimestampMixin, Base):
    """Maps an industry name found in a source to the standard industry (D-076)."""

    __tablename__ = "industry_mappings"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Lowercased, trimmed source text.
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    standard_industry: Mapped[str] = mapped_column(String(255), nullable=False)
    naics_sector: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        UniqueConstraint("source_name", name="uq_industry_mappings_source_name"),
        CheckConstraint(
            "source_name = lower(source_name)", name="ck_industry_mappings_source_lowercase"
        ),
    )


class StateMapping(TimestampMixin, Base):
    """Maps a state name or abbreviation found in a source to the standard name (D-078)."""

    __tablename__ = "state_mappings"

    id: Mapped[uuid.UUID] = uuid_pk()
    country: Mapped[str] = mapped_column(String(128), nullable=False)
    # Lowercased, trimmed source text.
    source_value: Mapped[str] = mapped_column(String(128), nullable=False)
    standard_name: Mapped[str] = mapped_column(String(128), nullable=False)
    abbreviation: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        UniqueConstraint("country", "source_value", name="uq_state_mappings_country_source"),
        CheckConstraint(
            "source_value = lower(source_value)", name="ck_state_mappings_source_lowercase"
        ),
    )
