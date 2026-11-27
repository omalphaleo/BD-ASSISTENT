"""Request and response models for the /reference-mappings API (Pydantic v2, M2-B6).

Needed so the industry and state mapping endpoints have a fixed, documented shape in
openapi.json and the generated frontend client used by the admin mappings page. Update
requests carry only the fields being changed (a key that is absent is left alone).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.leads.models import IndustryMapping, StateMapping


class IndustryMappingResponse(BaseModel):
    """One industry mapping row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_name: str
    standard_industry: str
    naics_sector: str | None
    updated_at: datetime

    @classmethod
    def from_row(cls, row: IndustryMapping) -> "IndustryMappingResponse":
        """Build the response from a database row."""
        return cls.model_validate(row)


class IndustryMappingListResponse(BaseModel):
    """One page of industry mappings."""

    items: list[IndustryMappingResponse]
    total: int
    limit: int
    offset: int


class CreateIndustryMappingRequest(BaseModel):
    """Body of POST /reference-mappings/industries."""

    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(min_length=1, max_length=255)
    standard_industry: str = Field(min_length=1, max_length=255)
    naics_sector: str | None = Field(default=None, max_length=16)


class UpdateIndustryMappingRequest(BaseModel):
    """Body of PATCH /reference-mappings/industries/{id}; send only what changes."""

    model_config = ConfigDict(extra="forbid")

    source_name: str | None = Field(default=None, min_length=1, max_length=255)
    standard_industry: str | None = Field(default=None, min_length=1, max_length=255)
    naics_sector: str | None = Field(default=None, max_length=16)

    @model_validator(mode="after")
    def _needs_a_change(self) -> "UpdateIndustryMappingRequest":
        """Reject an empty body: there would be nothing to change."""
        if not self.model_fields_set:
            raise ValueError("send at least one field to change")
        return self


class StateMappingResponse(BaseModel):
    """One state mapping row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    country: str
    source_value: str
    standard_name: str
    abbreviation: str | None
    updated_at: datetime

    @classmethod
    def from_row(cls, row: StateMapping) -> "StateMappingResponse":
        """Build the response from a database row."""
        return cls.model_validate(row)


class StateMappingListResponse(BaseModel):
    """One page of state mappings."""

    items: list[StateMappingResponse]
    total: int
    limit: int
    offset: int


class CreateStateMappingRequest(BaseModel):
    """Body of POST /reference-mappings/states."""

    model_config = ConfigDict(extra="forbid")

    country: str = Field(min_length=1, max_length=128)
    source_value: str = Field(min_length=1, max_length=128)
    standard_name: str = Field(min_length=1, max_length=128)
    abbreviation: str | None = Field(default=None, max_length=16)


class UpdateStateMappingRequest(BaseModel):
    """Body of PATCH /reference-mappings/states/{id}; send only what changes."""

    model_config = ConfigDict(extra="forbid")

    country: str | None = Field(default=None, min_length=1, max_length=128)
    source_value: str | None = Field(default=None, min_length=1, max_length=128)
    standard_name: str | None = Field(default=None, min_length=1, max_length=128)
    abbreviation: str | None = Field(default=None, max_length=16)

    @model_validator(mode="after")
    def _needs_a_change(self) -> "UpdateStateMappingRequest":
        """Reject an empty body: there would be nothing to change."""
        if not self.model_fields_set:
            raise ValueError("send at least one field to change")
        return self
