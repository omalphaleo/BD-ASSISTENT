"""SQLAlchemy models for the compliance module: opt-outs, the sending gate and erasure records.

Needed so the M3 eligibility service can block opted-out addresses (D-066), the M8 gate can
refuse real sending until its checklist passes (D-081), and erase-person can leave proof
without personal data (D-099). Migration 0008 creates the same schema and seeds the single
gate row and its four checklist rows. Tables only in M1 task A5: no service reads or writes
them yet. EligibilitySnapshot is deliberately not built (planned, no requirement needs it).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import now
from app.core.model_helpers import TimestampMixin, enum_column, in_check, uuid_pk
from app.db import Base


class OptOutSource(enum.StrEnum):
    """Where an opt-out came from (D-066)."""

    MANUAL = "manual"  # a BD user added it by hand
    IMPORTED = "imported"  # came in with an import file
    REPLY = "reply"  # the prospect asked to stop in a reply


class ChecklistItemKey(enum.StrEnum):
    """The four conditions that must pass before real sending can be switched on (D-081)."""

    M365_CONNECTED = "m365_connected"
    UNSUBSCRIBE_TESTED = "unsubscribe_tested"
    FOOTER_SAVED = "footer_saved"
    POSTAL_ADDRESS_SAVED = "postal_address_saved"


class OptOut(Base):
    """One opt-out event for an email address; the only enforced suppression (D-066).

    Keyed by the normalized address, with no link to people: it must survive erase-person
    (D-099) and cover addresses that have no person yet. A removal sets removed_at (soft
    removal, manager/admin only, with a reason); the partial unique index then lets the same
    address opt out again as a new row, so the earlier removal stays on record.
    """

    __tablename__ = "opt_outs"

    id: Mapped[uuid.UUID] = uuid_pk()
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    source: Mapped[OptOutSource] = mapped_column(enum_column(OptOutSource), nullable=False)
    # Free text; imported opt-out lists may not carry one.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SET NULL keeps the opt-out when the user who recorded or removed it is deleted.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_opt_outs_created_by_users"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_opt_outs_removed_by_users"),
        nullable=True,
    )
    removal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        in_check("source", OptOutSource, "ck_opt_outs_source_valid"),
        CheckConstraint(
            "email_normalized = lower(email_normalized)",
            name="ck_opt_outs_email_normalized_lowercase",
        ),
        # A removal must say when and why (D-066). removed_by is not required here because
        # SET NULL clears it if that user is later deleted.
        CheckConstraint(
            "removed_at IS NULL OR removal_reason IS NOT NULL",
            name="ck_opt_outs_removal_has_reason",
        ),
        CheckConstraint(
            "removed_at IS NOT NULL OR (removed_by IS NULL AND removal_reason IS NULL)",
            name="ck_opt_outs_removal_fields_together",
        ),
        # At most one active opt-out per address; the send-time check reads this index.
        Index(
            "uq_opt_outs_active_email_normalized",
            "email_normalized",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index("ix_opt_outs_email_normalized", "email_normalized"),
        Index("ix_opt_outs_created_by", "created_by"),
        Index("ix_opt_outs_removed_by", "removed_by"),
    )


class ComplianceGateStatus(TimestampMixin, Base):
    """The single row saying whether real sending is switched on (D-081).

    Migration 0008 seeds the row with real_sending_enabled = false, so readers never face a
    missing row. The `singleton` flag with a unique index and a CHECK makes a second row
    impossible. Activation history lives in the audit log; the kill switch is left to M8.
    """

    __tablename__ = "compliance_gate_status"

    id: Mapped[uuid.UUID] = uuid_pk()
    singleton: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    real_sending_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enabled_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_compliance_gate_status_enabled_by"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint("singleton", name="ck_compliance_gate_status_singleton_true"),
        Index("uq_compliance_gate_status_singleton", "singleton", unique=True),
        # Enabled state and its timestamp move together.
        CheckConstraint(
            "real_sending_enabled = (enabled_at IS NOT NULL)",
            name="ck_compliance_gate_status_enabled_has_timestamp",
        ),
    )


class ComplianceChecklistItem(TimestampMixin, Base):
    """One of the four D-081 conditions for real sending, seeded by migration 0008.

    The key set is closed (named CHECK), so the gate cannot be weakened by removing an item;
    adding a fifth item later is a new migration.
    """

    __tablename__ = "compliance_checklist_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    item_key: Mapped[ChecklistItemKey] = mapped_column(
        enum_column(ChecklistItemKey), nullable=False
    )
    is_passed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    passed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    passed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_compliance_checklist_items_passed_by"),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        in_check("item_key", ChecklistItemKey, "ck_compliance_checklist_items_item_key_valid"),
        CheckConstraint(
            "is_passed = (passed_at IS NOT NULL)",
            name="ck_compliance_checklist_items_passed_has_timestamp",
        ),
        Index("uq_compliance_checklist_items_item_key", "item_key", unique=True),
        Index("ix_compliance_checklist_items_passed_by", "passed_by"),
    )


class ErasureRecord(Base):
    """Proof that a person was erased (D-099), holding no personal data.

    former_person_id is a plain UUID with no foreign key because the person row is gone;
    the erased address stays only in opt_outs. removed_counts says how much was removed per
    area (for example raw_rows, emails, replies).
    """

    __tablename__ = "erasure_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    former_person_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    erased_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_erasure_records_erased_by_users"),
        nullable=True,
    )
    erased_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    removed_counts: Mapped[object] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        Index("ix_erasure_records_former_person_id", "former_person_id"),
        Index("ix_erasure_records_erased_by", "erased_by"),
    )
