"""The seam between the import workstream (W1) and the data-quality workstream (W2).

Needed so the two developers build in parallel against one frozen set of types: W1 turns
file rows into SourceRow objects and counts the RowOutcome it gets back, W2 implements
ingest_row (leads/ingest.py). Only types live here, no logic. After M2-0 this file changes
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


class IngestRow(Protocol):
    """The signature W2's ingest_row must satisfy (leads/ingest.py, task M2-B4).

    The function normalises, validates, quarantines, matches, merges or flags a possible
    duplicate, applies the engagement-history rules and writes the ImportChange row when an
    existing person changed. It never commits: the caller owns the transaction.
    """

    def __call__(self, session: Session, row: SourceRow, ctx: ImportContext) -> RowOutcome:
        """Process one row and report what happened to it."""
        ...
