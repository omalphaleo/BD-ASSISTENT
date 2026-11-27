"""Service for the industry and state reference mappings (M2-B6, D-076, D-078).

Needed so an admin can teach the app new industry and state wordings without a code change:
a mapping turns a source wording ("Software Dev", "calif.") into the standard value that
imports and search use. This module lists, adds and edits IndustryMapping and StateMapping
rows. Source wordings are stored lowercase and trimmed (the tables' CHECKs require it) and
are unique, so one wording never maps two ways. Every change is audited and committed here;
the routes in mappings_api.py are thin wrappers and enforce MANAGE_SOURCE_PROFILES.
Mappings hold no personal data, so audit summaries may name the wording.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.services import AuditAction, record
from app.core.models import User
from app.leads.models import IndustryMapping, StateMapping

INDUSTRY_KIND = "industry"
STATE_KIND = "state"
AUDIT_OBJECT_TYPE = "reference_mapping"


class MappingNotFoundError(Exception):
    """The mapping id does not exist."""


class MappingExistsError(Exception):
    """Another mapping already uses this source wording (and country, for states)."""


class MappingValueError(Exception):
    """A required value is blank after trimming."""


def _clean(value: str | None) -> str | None:
    """Trim a value; None for missing or blank."""
    if value is None:
        return None
    return value.strip() or None


def _required(value: str | None, name: str) -> str:
    """Return a trimmed required value.

    Raises:
        MappingValueError: If it is missing or blank.
    """
    cleaned = _clean(value)
    if cleaned is None:
        raise MappingValueError(f"{name} must not be blank")
    return cleaned


def _page[Row: IndustryMapping | StateMapping](
    db: Session,
    model: type[Row],
    order_by: Any,
    search: str | None,
    column: Any,
    limit: int,
    offset: int,
) -> tuple[list[Row], int]:
    """Return one page of mappings, optionally only those whose wording contains `search`."""
    query = select(model)
    count = select(func.count()).select_from(model)
    needle = _clean(search)
    if needle is not None:
        condition = column.ilike(f"%{needle.lower()}%")
        query = query.where(condition)
        count = count.where(condition)
    rows = db.scalars(query.order_by(*order_by).limit(limit).offset(offset)).all()
    return list(rows), db.scalar(count) or 0


def _audit(
    db: Session,
    actor: User,
    kind: str,
    mapping_id: uuid.UUID,
    summary: Mapping[str, object],
    ip_address: str | None,
) -> None:
    """Write the audit event for a mapping change (names the wording, never lead data)."""
    record(
        db,
        action=AuditAction.REFERENCE_MAPPING_CHANGED,
        actor_user_id=actor.id,
        object_type=AUDIT_OBJECT_TYPE,
        object_id=str(mapping_id),
        summary={"kind": kind, **summary},
        ip_address=ip_address,
    )


def _save(db: Session) -> None:
    """Flush and commit; a duplicate wording becomes MappingExistsError.

    Raises:
        MappingExistsError: If the unique constraint on the wording was hit.
    """
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise MappingExistsError from error
    db.commit()


# --- industries ----------------------------------------------------------------------------


def list_industry_mappings(
    db: Session, *, search: str | None, limit: int, offset: int
) -> tuple[list[IndustryMapping], int]:
    """List industry mappings by source wording, optionally filtered by a text search."""
    return _page(
        db,
        IndustryMapping,
        (IndustryMapping.source_name,),
        search,
        IndustryMapping.source_name,
        limit,
        offset,
    )


def create_industry_mapping(
    db: Session,
    actor: User,
    *,
    source_name: str,
    standard_industry: str,
    naics_sector: str | None,
    ip_address: str | None = None,
) -> IndustryMapping:
    """Add an industry mapping (D-076); the wording is stored lowercase.

    Raises:
        MappingValueError: If the wording or the standard industry is blank.
        MappingExistsError: If the wording already has a mapping.
    """
    mapping = IndustryMapping(
        source_name=_required(source_name, "source_name").lower(),
        standard_industry=_required(standard_industry, "standard_industry"),
        naics_sector=_clean(naics_sector),
    )
    db.add(mapping)
    _save(db)
    _audit(
        db,
        actor,
        INDUSTRY_KIND,
        mapping.id,
        {"change": "created", "source_name": mapping.source_name},
        ip_address,
    )
    db.commit()
    return mapping


def update_industry_mapping(
    db: Session,
    actor: User,
    mapping_id: uuid.UUID,
    changes: Mapping[str, str | None],
    *,
    ip_address: str | None = None,
) -> IndustryMapping:
    """Edit the given fields of an industry mapping (only the keys present are changed).

    Raises:
        MappingNotFoundError: If the id does not exist.
        MappingValueError: If a required value is blank.
        MappingExistsError: If the new wording belongs to another mapping.
    """
    mapping = db.get(IndustryMapping, mapping_id, with_for_update=True)
    if mapping is None:
        raise MappingNotFoundError
    if "source_name" in changes:
        mapping.source_name = _required(changes["source_name"], "source_name").lower()
    if "standard_industry" in changes:
        mapping.standard_industry = _required(changes["standard_industry"], "standard_industry")
    if "naics_sector" in changes:
        mapping.naics_sector = _clean(changes["naics_sector"])
    _save(db)
    _audit(
        db,
        actor,
        INDUSTRY_KIND,
        mapping.id,
        {"change": "updated", "fields": sorted(changes)},
        ip_address,
    )
    db.commit()
    return mapping


# --- states --------------------------------------------------------------------------------


def list_state_mappings(
    db: Session, *, search: str | None, limit: int, offset: int
) -> tuple[list[StateMapping], int]:
    """List state mappings by country and source wording, optionally filtered by a search."""
    return _page(
        db,
        StateMapping,
        (StateMapping.country, StateMapping.source_value),
        search,
        StateMapping.source_value,
        limit,
        offset,
    )


def create_state_mapping(
    db: Session,
    actor: User,
    *,
    country: str,
    source_value: str,
    standard_name: str,
    abbreviation: str | None,
    ip_address: str | None = None,
) -> StateMapping:
    """Add a state mapping (D-078); the wording is stored lowercase.

    Raises:
        MappingValueError: If the country, wording or standard name is blank.
        MappingExistsError: If that wording already has a mapping for the country.
    """
    mapping = StateMapping(
        country=_required(country, "country"),
        source_value=_required(source_value, "source_value").lower(),
        standard_name=_required(standard_name, "standard_name"),
        abbreviation=_clean(abbreviation),
    )
    db.add(mapping)
    _save(db)
    _audit(
        db,
        actor,
        STATE_KIND,
        mapping.id,
        {"change": "created", "source_value": mapping.source_value},
        ip_address,
    )
    db.commit()
    return mapping


def update_state_mapping(
    db: Session,
    actor: User,
    mapping_id: uuid.UUID,
    changes: Mapping[str, str | None],
    *,
    ip_address: str | None = None,
) -> StateMapping:
    """Edit the given fields of a state mapping (only the keys present are changed).

    Raises:
        MappingNotFoundError: If the id does not exist.
        MappingValueError: If a required value is blank.
        MappingExistsError: If the new wording belongs to another mapping of the country.
    """
    mapping = db.get(StateMapping, mapping_id, with_for_update=True)
    if mapping is None:
        raise MappingNotFoundError
    if "country" in changes:
        mapping.country = _required(changes["country"], "country")
    if "source_value" in changes:
        mapping.source_value = _required(changes["source_value"], "source_value").lower()
    if "standard_name" in changes:
        mapping.standard_name = _required(changes["standard_name"], "standard_name")
    if "abbreviation" in changes:
        mapping.abbreviation = _clean(changes["abbreviation"])
    _save(db)
    _audit(
        db,
        actor,
        STATE_KIND,
        mapping.id,
        {"change": "updated", "fields": sorted(changes)},
        ip_address,
    )
    db.commit()
    return mapping
