"""Request and response models for the /duplicates API (Pydantic v2, M2-B5).

Needed so the duplicate-review endpoints have a fixed, documented shape in openapi.json and
the generated frontend client: the screen shows both people side by side with the suggested
side per field, and sends the survivor and the chosen values to merge.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.leads.duplicates import CandidateView, PersonCard
from app.leads.models import DuplicateStatus


class DuplicateStatusFilter(StrEnum):
    """Which pairs the list shows."""

    OPEN = "open"
    NOT_DUPLICATE = "not_duplicate"

    def to_status(self) -> DuplicateStatus:
        """Return the matching stored status."""
        return DuplicateStatus(self.value)


class PersonCardResponse(BaseModel):
    """One person of a pair: the mergeable fields as text, plus all addresses."""

    id: uuid.UUID
    fields: dict[str, str | None]
    emails: list[str]
    company_name: str | None
    owner_id: uuid.UUID | None
    updated_at: datetime

    @classmethod
    def from_card(cls, card: PersonCard, field_names: tuple[str, ...]) -> "PersonCardResponse":
        """Build the response from a service result."""
        person = card.person
        return cls(
            id=person.id,
            fields={
                name: None if getattr(person, name) is None else str(getattr(person, name))
                for name in field_names
            },
            emails=card.emails,
            company_name=card.company_name,
            owner_id=person.owner_id,
            updated_at=person.updated_at,
        )


class DuplicateCandidateResponse(BaseModel):
    """A duplicate pair with both people and the pre-selected side per field."""

    model_config = ConfigDict(use_enum_values=True)

    id: uuid.UUID
    reason: str
    status: DuplicateStatus
    created_at: datetime
    decided_at: datetime | None
    person_a: PersonCardResponse
    person_b: PersonCardResponse
    # For each mergeable field, the side ("a" or "b") holding the most recent non-blank value.
    suggested: dict[str, Literal["a", "b"]]

    @classmethod
    def from_view(cls, view: CandidateView) -> "DuplicateCandidateResponse":
        """Build the response from a service result."""
        names = tuple(view.suggested)
        candidate = view.candidate
        return cls(
            id=candidate.id,
            reason=candidate.reason,
            status=candidate.status,
            created_at=candidate.created_at,
            decided_at=candidate.decided_at,
            person_a=PersonCardResponse.from_card(view.person_a, names),
            person_b=PersonCardResponse.from_card(view.person_b, names),
            suggested=view.suggested,
        )


class DuplicateListResponse(BaseModel):
    """One page of duplicate pairs."""

    items: list[DuplicateCandidateResponse]
    total: int
    limit: int
    offset: int


class MergeDuplicateRequest(BaseModel):
    """Body of POST /duplicates/{id}/merge."""

    model_config = ConfigDict(extra="forbid")

    survivor_id: uuid.UUID
    # Chosen value per field name; a missing or blank field gets the most recent value.
    values: dict[str, str | None] = Field(default_factory=dict, max_length=32)


class MergeDuplicateResponse(BaseModel):
    """What the merge did: the kept person, the absorbed one and the history record."""

    survivor_id: uuid.UUID
    absorbed_person_id: uuid.UUID
    merge_record_id: uuid.UUID
