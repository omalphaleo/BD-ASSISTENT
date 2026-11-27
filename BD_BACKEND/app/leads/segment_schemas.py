"""Request and response shapes of saved segments (M3-A4).

Needed so the segments endpoints, the generated frontend client and the search page agree on one
contract. Pydantic v2 models only; no logic lives here. A segment stores a FilterSet, the same
object the search endpoint takes, so a saved filter can never describe more than a live search.
"""

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from app.leads.filters import FilterSet
from app.leads.models import SegmentVisibility

MAX_SEGMENT_NAME_LENGTH = 255  # matches the segments.name column

# Trimmed and non-empty: a blank name is rejected rather than saved as an unreadable row.
SegmentName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SEGMENT_NAME_LENGTH),
]


class SegmentCreate(BaseModel):
    """A new segment: a name, the filters to save and who may see it (private by default, D-098)."""

    model_config = ConfigDict(extra="forbid")

    name: SegmentName
    filters: FilterSet
    visibility: SegmentVisibility = SegmentVisibility.PRIVATE


class SegmentUpdate(BaseModel):
    """Rename and/or share or unshare a segment. At least one field must be given.

    Filters cannot be changed (Decision 7 of the M3-A4 plan): save a new segment instead.
    """

    model_config = ConfigDict(extra="forbid")

    name: SegmentName | None = None
    visibility: SegmentVisibility | None = None

    @model_validator(mode="after")
    def _require_a_change(self) -> Self:
        """Reject an empty update.

        Raises:
            ValueError: neither name nor visibility was given.
        """
        if self.name is None and self.visibility is None:
            raise ValueError("give a name, a visibility or both")
        return self


class SegmentOwner(BaseModel):
    """The rep who owns the segment; the sign-in email is the only display name stored."""

    id: uuid.UUID
    email: str


class SegmentResponse(BaseModel):
    """One segment as the search page shows it."""

    id: uuid.UUID
    name: str
    visibility: SegmentVisibility
    # None when the owner's user row was deleted (owner_id is SET NULL).
    owner: SegmentOwner | None
    # Whether the caller may rename, share or delete it; the server re-checks on every write.
    can_edit: bool
    # False when the stored filters no longer pass FilterSet; `filters` is then null and the
    # screen disables Apply, while rename, share and delete still work.
    filters_valid: bool
    filters: FilterSet | None
    created_at: datetime
    updated_at: datetime


class SegmentListResponse(BaseModel):
    """Every segment the caller may see: their own plus the ones shared with the team."""

    items: list[SegmentResponse]
