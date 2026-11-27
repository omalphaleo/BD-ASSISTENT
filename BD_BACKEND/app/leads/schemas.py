"""Request and response models for the /quarantine API (Pydantic v2, M2-B2).

Needed so the quarantine endpoints have a fixed, documented shape in openapi.json and the
generated frontend client; the screen shows these fields and sends FixQuarantineRequest.
Later W2 tasks (duplicates, reference mappings) add their models here too.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.leads.contracts import JsonScalar
from app.leads.models import QuarantineStatus
from app.leads.quarantine import MAX_PAYLOAD_FIELDS, QuarantineItem, ReleaseResult


class QuarantineStatusFilter(StrEnum):
    """Which records the list shows; "all" adds the released and discarded ones."""

    OPEN = "open"
    RELEASED = "released"
    DISCARDED = "discarded"
    ALL = "all"

    def to_status(self) -> QuarantineStatus | None:
        """Return the matching status, or None for "all"."""
        return None if self is QuarantineStatusFilter.ALL else QuarantineStatus(self.value)


class QuarantineRecordResponse(BaseModel):
    """One quarantined row as shown on the quarantine screen."""

    model_config = ConfigDict(use_enum_values=True)

    id: uuid.UUID
    status: QuarantineStatus
    # Reason codes still failing, for example ["personal_email_only"]; empty means "ready".
    issues: list[str]
    # The row's values keyed by app field name, as BD has edited them.
    payload: dict[str, JsonScalar]
    import_file_id: uuid.UUID | None
    filename: str | None
    row_number: int | None
    uploaded_by: uuid.UUID | None
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: uuid.UUID | None

    @classmethod
    def from_item(cls, item: QuarantineItem) -> "QuarantineRecordResponse":
        """Build the response from a service result."""
        record = item.record
        payload = record.payload if isinstance(record.payload, dict) else {}
        return cls(
            id=record.id,
            status=record.status,
            issues=list(record.issues),
            payload=payload,
            import_file_id=item.import_file_id,
            filename=item.filename,
            row_number=item.row_number,
            uploaded_by=item.uploaded_by,
            created_at=record.created_at,
            resolved_at=record.resolved_at,
            resolved_by=record.resolved_by,
        )


class QuarantineListResponse(BaseModel):
    """A page of quarantined rows."""

    items: list[QuarantineRecordResponse]
    total: int
    limit: int
    offset: int


class FixQuarantineRequest(BaseModel):
    """Fields to change on an open record; a blank text value clears the field."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, JsonScalar] = Field(min_length=1, max_length=MAX_PAYLOAD_FIELDS)


class ReleaseQuarantineResponse(BaseModel):
    """The result of a release attempt."""

    model_config = ConfigDict(use_enum_values=True)

    # False when the row still has issues or ingest_row refused it; the record stays open.
    released: bool
    # What ingest_row did ("imported", "updated", ...), or null when validation failed first.
    outcome: str | None
    record: QuarantineRecordResponse

    @classmethod
    def from_result(cls, result: ReleaseResult) -> "ReleaseQuarantineResponse":
        """Build the response from a service result."""
        return cls(
            released=result.released,
            outcome=result.outcome.value if result.outcome else None,
            record=QuarantineRecordResponse.from_item(result.item),
        )
