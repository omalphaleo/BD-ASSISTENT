"""Test factories for the content tables: voice, profiles, knowledge base, structures, versions.

Needed so tests build valid synthetic content rows in one line and override only the field a
test is about (M1 task B11). Tables with a fixed set of keys (size profiles, industry profiles,
email structures) pick the first key not yet used, because their key is unique; the voice is
a single row, so its factory returns the existing one. All data is synthetic.
"""

import enum
import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.models import (
    EMBEDDING_DIMENSION,
    ConfigType,
    ConfigVersion,
    EmailStructure,
    EmailStructureStep,
    IndustryProfile,
    IndustryProfileItem,
    IndustryProfileKey,
    KnowledgeEmbedding,
    KnowledgeItem,
    KnowledgeItemType,
    SectionKind,
    SizeProfile,
    SizeProfileKey,
    StructureSection,
    VoiceSetting,
)
from factories.common import next_number, persist


def _first_unused[Key: enum.StrEnum](
    session: Session, model: type, column: str, keys: type[Key]
) -> Key:
    """Return the first member of the key enum that no row of the model uses yet.

    Raises:
        RuntimeError: if every key is taken (the table's unique key allows no more rows).
    """
    used = set(session.scalars(select(getattr(model, column))))
    for key in keys:
        if key not in used:
            return key
    raise RuntimeError(f"All {model.__name__} keys are already used; pass a key or reuse a row")


def make_voice_setting(session: Session, **overrides: object) -> VoiceSetting:
    """Return the single voice row, creating it (with overrides) when none exists yet."""
    existing = session.scalars(select(VoiceSetting)).first()
    if existing is not None:
        return existing
    fields: dict[str, object] = {"tone": "clear, practical, peer-to-peer"}
    return persist(session, VoiceSetting(**{**fields, **overrides}))


def make_size_profile(session: Session, **overrides: object) -> SizeProfile:
    """Insert a size profile for the first unused size key (at most three rows exist)."""
    key = overrides.get("key") or _first_unused(session, SizeProfile, "key", SizeProfileKey)
    fields: dict[str, object] = {"key": key, "name": f"Size profile {key}", "min_employees": 1}
    return persist(session, SizeProfile(**{**fields, **overrides}))


def make_industry_profile(session: Session, **overrides: object) -> IndustryProfile:
    """Insert an industry profile for the first unused industry key (at most six rows exist)."""
    key = overrides.get("key") or _first_unused(session, IndustryProfile, "key", IndustryProfileKey)
    fields: dict[str, object] = {"key": key, "name": f"Industry profile {key}"}
    return persist(session, IndustryProfile(**{**fields, **overrides}))


def _hash(text: str) -> str:
    """Return the SHA-256 hex digest (64 characters) used for content hashes."""
    return hashlib.sha256(text.encode()).hexdigest()


def make_knowledge_item(session: Session, **overrides: object) -> KnowledgeItem:
    """Insert a draft solution item with a unique title and a matching content hash."""
    number = next_number()
    body = f"Synthetic solution description {number}."
    fields: dict[str, object] = {
        "type": KnowledgeItemType.SOLUTION,
        "title": f"Solution {number}",
        "body": body,
        "content_hash": _hash(body),
    }
    return persist(session, KnowledgeItem(**{**fields, **overrides}))


def make_knowledge_embedding(
    session: Session, *, item: KnowledgeItem | None = None, **overrides: object
) -> KnowledgeEmbedding:
    """Insert the vector of an item (a new item if none is given), all zeros but one value."""
    item = item or make_knowledge_item(session)
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[0] = 1.0
    fields: dict[str, object] = {
        "knowledge_item_id": item.id,
        "embedding": vector,
        "model_name": "test-embedding-model",
        "dimension": EMBEDDING_DIMENSION,
        "content_hash": item.content_hash,
    }
    return persist(session, KnowledgeEmbedding(**{**fields, **overrides}))


def make_industry_profile_item(
    session: Session,
    *,
    profile: IndustryProfile | None = None,
    item: KnowledgeItem | None = None,
    **overrides: object,
) -> IndustryProfileItem:
    """Link an industry profile and a knowledge item (new ones if none are given)."""
    fields: dict[str, object] = {
        "industry_profile_id": (profile or make_industry_profile(session)).id,
        "knowledge_item_id": (item or make_knowledge_item(session)).id,
    }
    return persist(session, IndustryProfileItem(**{**fields, **overrides}))


def make_email_structure(session: Session, **overrides: object) -> EmailStructure:
    """Insert a structure for the first unused email step (at most three rows exist)."""
    step = overrides.get("step") or _first_unused(
        session, EmailStructure, "step", EmailStructureStep
    )
    fields: dict[str, object] = {"step": step, "name": f"Structure {step}", "max_words": 120}
    return persist(session, EmailStructure(**{**fields, **overrides}))


def make_structure_section(
    session: Session, *, structure: EmailStructure | None = None, **overrides: object
) -> StructureSection:
    """Insert a fixed section for the structure (a new one if none) at the next position."""
    structure = structure or make_email_structure(session)
    position = (
        len(list(session.scalars(select(StructureSection.id).filter_by(structure_id=structure.id))))
        + 1
    )
    fields: dict[str, object] = {
        "structure_id": structure.id,
        "position": position,
        "kind": SectionKind.FIXED,
        "name": f"Section {position}",
    }
    return persist(session, StructureSection(**{**fields, **overrides}))


def make_config_version(session: Session, **overrides: object) -> ConfigVersion:
    """Insert version 1 of a voice configuration with a fresh config id and an empty snapshot."""
    fields: dict[str, object] = {
        "config_type": ConfigType.VOICE,
        "config_id": uuid.uuid4(),
        "version_number": 1,
        "snapshot": {},
    }
    return persist(session, ConfigVersion(**{**fields, **overrides}))
