"""The seam between the import workstream (W1) and the data-quality workstream (W2).

Needed so the two developers build in parallel against one frozen set of types: W1 turns
file rows into SourceRow objects and counts the RowOutcome it gets back, W2 implements
ingest_row (leads/ingest.py). Only types and the canonical field registry (TARGET_FIELDS, the
keys of SourceRow.values, added in M2-A2) live here, no logic. After M2-0 this file changes
only through a pull request both developers approve (m2.md sections 17 and 18).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from sqlalchemy.orm import Session

# A single cell value as stored in JSON: what a SourceRow or a FieldChange may carry.
JsonScalar = str | int | float | bool | None


class IngestSource(StrEnum):
    """Where an ingest_row call comes from, so one pipeline serves both entry points."""

    IMPORT = "import"
    QUARANTINE_RELEASE = "quarantine_release"


class RowOutcomeKind(StrEnum):
    """What ingest_row did with one row; W1 only counts these into the ImportReport."""

    IMPORTED = "imported"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    QUARANTINED = "quarantined"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class SourceRow:
    """One uploaded row after column mapping, handed from W1 to W2.

    The original, unmodified row is already stored in raw_rows by W1 (D-099) under
    (import_file_id, row_number); W2 finds it there when it needs to link a quarantine
    record. W2 never parses files or touches ImportFile.

    Attributes:
        row_number: One-based position of the row in the sheet.
        values: The row's values keyed by app field name (the mapping is already applied).
        raw_email: The email text exactly as it appeared in the file, before normalisation.
        import_file_id: The ImportFile this row belongs to.
        source_profile_id: The SourceProfile chosen for the file, or None when none was.
        default_country: Country used when the row has none, as chosen in the wizard.
    """

    row_number: int
    values: Mapping[str, JsonScalar]
    raw_email: str | None
    import_file_id: uuid.UUID
    source_profile_id: uuid.UUID | None
    default_country: str | None


@dataclass(frozen=True, slots=True)
class ImportContext:
    """Per-call settings that are not part of the row itself.

    Attributes:
        import_file_id: The import this call belongs to.
        uploaded_by: The user who uploaded the file, or None if that user was deleted.
        now: The current time from core.clock.now(); passed in so tests control it.
        cooling_off_days: Days after contact before a person may enter a new campaign.
        source: Whether the call comes from an import or from a quarantine release.
    """

    import_file_id: uuid.UUID
    uploaded_by: uuid.UUID | None
    now: datetime
    cooling_off_days: int
    source: IngestSource


@dataclass(frozen=True, slots=True)
class RowOutcome:
    """The result of ingest_row for one row.

    Attributes:
        kind: What happened to the row.
        reason_code: Short machine-readable reason (for example "personal_email_only"),
            present for quarantined, rejected and possible-duplicate rows.
        person_id: The person created, updated or matched, when there is one.
    """

    kind: RowOutcomeKind
    reason_code: str | None = None
    person_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class FieldChange:
    """One changed field of an updated person; the JSON item stored in ImportChange.changes.

    ImportChange.changes holds a list of these, serialised as {"field", "old", "new"}
    objects. W2 writes them, W1's report page reads them.
    """

    field: str
    old: JsonScalar
    new: JsonScalar


class FieldType(StrEnum):
    """The JSON type W1 delivers for a target field (the conversion W1 is allowed to do).

    DATETIME values are ISO-8601 text: JsonScalar has no date type, and W2 attaches the zone.
    List-like fields (technologies, keywords, lists) stay TEXT exactly as received; W2 splits.
    """

    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATETIME = "datetime"


class FieldGroup(StrEnum):
    """Which part of the lead a target field describes (used to group the mapping screen)."""

    PERSON = "person"
    EMAIL = "email"
    PHONE = "phone"
    ENGAGEMENT = "engagement"
    COMPANY = "company"


@dataclass(frozen=True, slots=True)
class TargetField:
    """One canonical field a source column may be mapped to (a key of SourceRow.values).

    Attributes:
        key: Stable snake_case name; the key W1 puts in SourceRow.values and W2 reads.
        group: Which part of the lead the field describes.
        value_type: The JSON type W1 delivers.
        required: True only for the two mandatory fields of D-069 (work email, first name).
        label: Human-readable name for the mapping screen.
    """

    key: str
    group: FieldGroup
    value_type: FieldType
    label: str
    required: bool = False


def _fields(
    group: FieldGroup, value_type: FieldType, *keys_and_labels: tuple[str, str]
) -> tuple[TargetField, ...]:
    """Build several TargetFields that share a group and a type."""
    return tuple(TargetField(key, group, value_type, label) for key, label in keys_and_labels)


_TEXT, _INT, _DEC, _BOOL, _DATE = (
    FieldType.TEXT,
    FieldType.INTEGER,
    FieldType.DECIMAL,
    FieldType.BOOLEAN,
    FieldType.DATETIME,
)

# The canonical field registry (m2.md section 18, Q-IMPORT-11). Mapping is by key, never by
# column position (D-040). Columns that map to no key stay in raw_rows only. Several emails and
# phones use fixed scalar keys because SourceRow.values is a flat map of scalars.
TARGET_FIELDS: tuple[TargetField, ...] = (
    # Person
    *_fields(
        FieldGroup.PERSON,
        _TEXT,
        ("source_record_id", "Source record ID (person)"),
        ("last_name", "Last name"),
        ("title", "Job title"),
        ("seniority", "Seniority"),
        ("department", "Department"),
        ("sub_department", "Sub department"),
        ("linkedin_url", "Person LinkedIn URL"),
        ("city", "City"),
        ("state", "State"),
        ("country", "Country"),
        ("owner_name", "Contact owner"),
        ("account_owner_name", "Account owner"),
    ),
    TargetField("first_name", FieldGroup.PERSON, _TEXT, "First name", required=True),
    # Emails: the primary one plus the secondary, tertiary and personal ones (D-072).
    TargetField("email", FieldGroup.EMAIL, _TEXT, "Email", required=True),
    *_fields(
        FieldGroup.EMAIL,
        _TEXT,
        ("email_status", "Email status"),
        ("email_source", "Email source"),
        ("email_verification_source", "Email verification source"),
        ("email_confidence", "Email confidence"),
        ("email_catch_all_status", "Email catch-all status"),
        ("secondary_email", "Secondary email"),
        ("secondary_email_status", "Secondary email status"),
        ("secondary_email_source", "Secondary email source"),
        ("secondary_email_verification_source", "Secondary email verification source"),
        ("tertiary_email", "Tertiary email"),
        ("tertiary_email_status", "Tertiary email status"),
        ("tertiary_email_source", "Tertiary email source"),
        ("tertiary_email_verification_source", "Tertiary email verification source"),
        ("personal_email", "Personal email"),
    ),
    *_fields(FieldGroup.EMAIL, _DATE, ("email_last_verified_at", "Email last verified at")),
    # Phones: all stored, none used in the MVP (Q-IMPORT-11).
    *_fields(
        FieldGroup.PHONE,
        _TEXT,
        ("phone_work_direct", "Work direct phone"),
        ("phone_home", "Home phone"),
        ("phone_mobile", "Mobile phone"),
        ("phone_corporate", "Corporate phone"),
        ("phone_other", "Other phone"),
        ("company_phone", "Company phone"),
    ),
    *_fields(FieldGroup.PHONE, _BOOL, ("do_not_call", "Do not call")),
    # Engagement history and source status (D-073, D-074).
    *_fields(
        FieldGroup.ENGAGEMENT,
        _TEXT,
        ("source_status", "Source status"),
        ("source_stage", "Source stage"),
        ("lists", "Source lists"),
        ("intent_primary_topic", "Primary intent topic"),
        ("intent_secondary_topic", "Secondary intent topic"),
    ),
    *_fields(
        FieldGroup.ENGAGEMENT,
        _BOOL,
        ("email_sent", "Email sent"),
        ("email_opened", "Email opened"),
        ("email_bounced", "Email bounced"),
        ("replied", "Replied"),
        ("demoed", "Demoed"),
        ("qualify_contact", "Qualify contact"),
    ),
    *_fields(
        FieldGroup.ENGAGEMENT,
        _DEC,
        ("intent_primary_score", "Primary intent score"),
        ("intent_secondary_score", "Secondary intent score"),
    ),
    *_fields(FieldGroup.ENGAGEMENT, _DATE, ("last_contacted_at", "Last contacted")),
    # Company
    *_fields(
        FieldGroup.COMPANY,
        _TEXT,
        ("company_source_id", "Source record ID (company)"),
        ("company_name", "Company name"),
        ("company_name_for_emails", "Company name for emails"),
        ("website", "Website"),
        ("industry", "Industry"),
        ("naics", "NAICS codes"),
        ("sic", "SIC codes"),
        ("latest_funding_round_type", "Latest funding round type"),
        ("technologies", "Technologies"),
        ("keywords", "Keywords"),
        ("company_linkedin_url", "Company LinkedIn URL"),
        ("company_facebook_url", "Company Facebook URL"),
        ("company_twitter_url", "Company Twitter URL"),
        ("company_address", "Company address"),
        ("company_city", "Company city"),
        ("company_state", "Company state"),
        ("company_country", "Company country"),
    ),
    *_fields(
        FieldGroup.COMPANY,
        _INT,
        ("employee_count", "Employee count"),
        ("founded_year", "Founded year"),
    ),
    *_fields(
        FieldGroup.COMPANY,
        _DEC,
        ("annual_revenue", "Annual revenue"),
        ("total_funding", "Total funding"),
        ("latest_funding_amount", "Latest funding amount"),
    ),
    *_fields(FieldGroup.COMPANY, _DATE, ("latest_funding_date", "Latest funding date")),
)

TARGET_FIELDS_BY_KEY: dict[str, TargetField] = {field.key: field for field in TARGET_FIELDS}
# The mandatory keys of D-069; a mapping without them cannot start an import.
REQUIRED_FIELD_KEYS: tuple[str, ...] = tuple(f.key for f in TARGET_FIELDS if f.required)


class IngestRow(Protocol):
    """The signature W2's ingest_row must satisfy (leads/ingest.py, task M2-B4).

    The function normalises, validates, quarantines, matches, merges or flags a possible
    duplicate, applies the engagement-history rules and writes the ImportChange row when an
    existing person changed. It never commits: the caller owns the transaction.
    """

    def __call__(self, session: Session, row: SourceRow, ctx: ImportContext) -> RowOutcome:
        """Process one row and report what happened to it."""
        ...
