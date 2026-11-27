"""SQLAlchemy models for the content module: voice, profiles, knowledge base, structures, versions.

Needed so M4 can store the writing guidance the AI drafts from: the global voice and the size
and industry profiles (D-085), the knowledge base with its pgvector embeddings (D-088), the
hybrid email structures (D-084, D-112) and the version snapshots that let admins restore
defaults (D-112). Migration 0009 creates the same schema. Tables only in M1 task B6: no
service reads or writes them yet and nothing is seeded. Fixed-value columns are VARCHAR plus a
named CHECK (not native enums), like the other modules.
"""

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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

# Size of every stored embedding vector. Chosen for the Gemini embedding model's reduced
# output size; changing it needs a new migration plus re-embedding (model_name and dimension
# are stored with each vector so a change is detectable).
EMBEDDING_DIMENSION = 768


class SizeProfileKey(enum.StrEnum):
    """The three company-size bands (D-085)."""

    SMB = "smb"  # 1-200 employees
    MID_MARKET = "mid_market"  # 201-1,000
    ENTERPRISE = "enterprise"  # above 1,000


class IndustryProfileKey(enum.StrEnum):
    """The industries with their own guidance, plus the General fallback (D-037, D-085)."""

    MANUFACTURING = "manufacturing"
    REAL_ESTATE = "real_estate"
    HOSPITALITY = "hospitality"
    HEALTHCARE = "healthcare"
    IT_SERVICES = "it_services"
    GENERAL = "general"


class KnowledgeItemType(enum.StrEnum):
    """Kind of knowledge item; case studies arrive once leadership approves them (D-088)."""

    SOLUTION = "solution"
    CASE_STUDY = "case_study"


class KnowledgeItemStatus(enum.StrEnum):
    """Lifecycle of a knowledge item; only approved items reach the AI (D-088)."""

    DRAFT = "draft"
    APPROVED = "approved"
    RETIRED = "retired"


class EmailStructureStep(enum.StrEnum):
    """Which email of the three-step sequence a structure describes (D-084)."""

    FIRST_EMAIL = "first_email"
    FOLLOW_UP_1 = "follow_up_1"
    FOLLOW_UP_2 = "follow_up_2"


class SectionKind(enum.StrEnum):
    """Whether the app inserts a section or the AI writes it (D-084, D-112)."""

    FIXED = "fixed"
    AI = "ai"


class ConfigType(enum.StrEnum):
    """What a ConfigVersion snapshot belongs to (D-112)."""

    VOICE = "voice"
    SIZE_PROFILE = "size_profile"
    INDUSTRY_PROFILE = "industry_profile"
    EMAIL_STRUCTURE = "email_structure"


class ProfileGuidanceMixin:
    """The guidance fields shared by size and industry profiles (Q-CONTENT-08, D-085).

    Free text, empty until an admin fills it in; the default texts are seeded by M4.
    """

    pain_points: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    # The offering(s) to lead with, from the four Alphaleo offerings (D-035).
    offerings: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    tone: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    avoid: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    example_phrases: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))


# --- Voice and profiles ---


class VoiceSetting(TimestampMixin, Base):
    """The one global voice: company description, differentiator, tone, banned words (D-085)."""

    __tablename__ = "voice_settings"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Always true; the unique index on it allows only one row (same trick as the compliance
    # gate), so "the voice" is never ambiguous.
    singleton: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    company_description: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    differentiator: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    tone: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    # Words the AI must never use; validators check drafts against this list.
    banned_words: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    # SET NULL keeps the voice when the admin who last edited it is deleted.
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_voice_settings_updated_by_users"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint("singleton", name="ck_voice_settings_singleton_true"),
        Index("uq_voice_settings_singleton", "singleton", unique=True),
        Index("ix_voice_settings_updated_by", "updated_by"),
    )


class SizeProfile(ProfileGuidanceMixin, TimestampMixin, Base):
    """Guidance for one company-size band, picked by the lead's employee count (D-085)."""

    __tablename__ = "size_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[SizeProfileKey] = mapped_column(enum_column(SizeProfileKey), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Inclusive employee range this profile applies to; no max means "and above".
    min_employees: Mapped[int] = mapped_column(Integer, nullable=False)
    max_employees: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        in_check("key", SizeProfileKey, "ck_size_profiles_key_valid"),
        CheckConstraint("min_employees >= 0", name="ck_size_profiles_min_employees_not_negative"),
        CheckConstraint(
            "max_employees IS NULL OR max_employees >= min_employees",
            name="ck_size_profiles_employee_range_ordered",
        ),
        UniqueConstraint("key", name="uq_size_profiles_key"),
    )


class IndustryProfile(ProfileGuidanceMixin, TimestampMixin, Base):
    """Guidance for one industry, or the General fallback (D-085)."""

    __tablename__ = "industry_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[IndustryProfileKey] = mapped_column(enum_column(IndustryProfileKey), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    __table_args__ = (
        in_check("key", IndustryProfileKey, "ck_industry_profiles_key_valid"),
        UniqueConstraint("key", name="uq_industry_profiles_key"),
    )


# --- Knowledge base ---


class KnowledgeItem(TimestampMixin, Base):
    """One knowledge-base entry (a solution description now, case studies later; D-088).

    Only approved items are given to the AI. Editing the body changes content_hash, which is
    how a stale embedding is detected (plan section 10).
    """

    __tablename__ = "knowledge_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    type: Mapped[KnowledgeItemType] = mapped_column(enum_column(KnowledgeItemType), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[KnowledgeItemStatus] = mapped_column(
        enum_column(KnowledgeItemStatus),
        nullable=False,
        default=KnowledgeItemStatus.DRAFT,
        server_default=text("'draft'"),
    )
    # SHA-256 hex of the body, computed by the knowledge service when the body is saved.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Which company sizes / industries the item is relevant to; retrieval filters on these.
    size_tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    industry_tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    # SET NULL keeps the item when the user who wrote or approved it is deleted.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_knowledge_items_created_by_users"),
        nullable=True,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_knowledge_items_approved_by_users"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        in_check("type", KnowledgeItemType, "ck_knowledge_items_type_valid"),
        in_check("status", KnowledgeItemStatus, "ck_knowledge_items_status_valid"),
        # The status must agree with its timestamps: approved needs approved_at, retired needs
        # retired_at (and keeps approved_at as history), draft and approved are never retired.
        CheckConstraint(
            "(status = 'draft' AND retired_at IS NULL)"
            " OR (status = 'approved' AND approved_at IS NOT NULL AND retired_at IS NULL)"
            " OR (status = 'retired' AND retired_at IS NOT NULL)",
            name="ck_knowledge_items_status_matches_timestamps",
        ),
        Index("ix_knowledge_items_status", "status"),
        Index("ix_knowledge_items_size_tags", "size_tags", postgresql_using="gin"),
        Index("ix_knowledge_items_industry_tags", "industry_tags", postgresql_using="gin"),
        Index("ix_knowledge_items_created_by", "created_by"),
        Index("ix_knowledge_items_approved_by", "approved_by"),
    )


class KnowledgeEmbedding(TimestampMixin, Base):
    """The vector for one knowledge item, with the model and hash it was made from.

    At most one per item. Retrieval uses only items whose embedding exists and whose
    content_hash equals the item's current hash. No vector index: exact search is enough at
    MVP volumes and one can be added later (plan section 10).
    """

    __tablename__ = "knowledge_embeddings"

    id: Mapped[uuid.UUID] = uuid_pk()
    knowledge_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "knowledge_items.id", ondelete="CASCADE", name="fk_knowledge_embeddings_item_id"
        ),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION), nullable=False)
    # Embedding model that produced the vector; a configured-model change flags old rows.
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    # Hash of the item body at embedding time; compared with knowledge_items.content_hash.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint(
            f"dimension = {EMBEDDING_DIMENSION}", name="ck_knowledge_embeddings_dimension_matches"
        ),
        UniqueConstraint("knowledge_item_id", name="uq_knowledge_embeddings_knowledge_item_id"),
    )


class IndustryProfileItem(Base):
    """Link saying an industry profile may draw on a knowledge item (Q-CONTENT-08)."""

    __tablename__ = "industry_profile_items"

    industry_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "industry_profiles.id", ondelete="CASCADE", name="fk_industry_profile_items_profile_id"
        ),
        primary_key=True,
    )
    knowledge_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "knowledge_items.id", ondelete="CASCADE", name="fk_industry_profile_items_item_id"
        ),
        primary_key=True,
    )

    __table_args__ = (Index("ix_industry_profile_items_knowledge_item_id", "knowledge_item_id"),)


# --- Email structures ---


class EmailStructure(TimestampMixin, Base):
    """The layout of one email in the sequence, with its word limits (D-084)."""

    __tablename__ = "email_structures"

    id: Mapped[uuid.UUID] = uuid_pk()
    step: Mapped[EmailStructureStep] = mapped_column(
        enum_column(EmailStructureStep), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # First email 80-120 words, follow-ups 70 and 50 at most (Q-CONTENT-07); no minimum for those.
    min_words: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_words: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        in_check("step", EmailStructureStep, "ck_email_structures_step_valid"),
        CheckConstraint("max_words > 0", name="ck_email_structures_max_words_positive"),
        CheckConstraint(
            "min_words IS NULL OR (min_words > 0 AND min_words <= max_words)",
            name="ck_email_structures_min_words_in_range",
        ),
        UniqueConstraint("step", name="uq_email_structures_step"),
    )


class StructureSection(TimestampMixin, Base):
    """One section of an email structure: fixed text the app inserts, or an AI instruction."""

    __tablename__ = "structure_sections"

    id: Mapped[uuid.UUID] = uuid_pk()
    structure_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "email_structures.id", ondelete="CASCADE", name="fk_structure_sections_structure_id"
        ),
        nullable=False,
    )
    # 1-based order inside the email.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[SectionKind] = mapped_column(enum_column(SectionKind), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # The exact text for a fixed section; the writing instruction for an AI section.
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    max_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Optional sections (the proof point) are left out when nothing approved fits.
    is_optional: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    __table_args__ = (
        in_check("kind", SectionKind, "ck_structure_sections_kind_valid"),
        CheckConstraint("position >= 1", name="ck_structure_sections_position_positive"),
        CheckConstraint(
            "max_chars IS NULL OR max_chars > 0", name="ck_structure_sections_max_chars_positive"
        ),
        # DEFERRABLE so an admin reordering sections can swap positions inside one transaction.
        UniqueConstraint(
            "structure_id",
            "position",
            name="uq_structure_sections_structure_id_position",
            deferrable=True,
            initially="DEFERRED",
        ),
    )


# --- Versions ---


class ConfigVersion(Base):
    """An immutable snapshot of a voice, profile or structure, taken on every admin edit.

    Lets admins view history and restore the defaults (D-112). config_id has no foreign key
    because it points at one of four different tables, chosen by config_type.
    """

    __tablename__ = "config_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    config_type: Mapped[ConfigType] = mapped_column(enum_column(ConfigType), nullable=False)
    config_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # 1 for the first snapshot of this configuration, then +1 per edit (set by the service).
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[object] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_config_versions_created_by_users"),
        nullable=True,
    )
    # Time comes only from core.clock.now(), so no server-side default.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )

    __table_args__ = (
        in_check("config_type", ConfigType, "ck_config_versions_config_type_valid"),
        CheckConstraint("version_number >= 1", name="ck_config_versions_version_number_positive"),
        UniqueConstraint(
            "config_type",
            "config_id",
            "version_number",
            name="uq_config_versions_config_type_config_id_version_number",
        ),
        Index("ix_config_versions_created_by", "created_by"),
    )
