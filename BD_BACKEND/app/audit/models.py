"""AuditLog model: one immutable row per sensitive action.

Needed so approvals, role changes and login failures can be reviewed later (plan §6.2,
§14.S); audit.services.record() writes these rows and Alembic migration 0004 creates the table.
Leaf module: imports only app.db and app.core.clock, never app.core.models.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import now
from app.db import Base


class AuditLog(Base):
    """One audit event. The table is append-only, enforced by PostgreSQL triggers.

    Triggers (migration 0004) reject UPDATE, DELETE and TRUNCATE, so history cannot be
    altered even by a bug or manual SQL.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    # Time comes only from core.clock.now(), so no server-side default.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )
    # Plain UUID, deliberately no foreign key: audit is a leaf module, and a FK would
    # couple it to users and block or cascade deletes against an append-only table.
    # NULL when there is no user, e.g. a failed login for an unknown email.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Text, not a DB enum: every milestone adds actions; allowed values live in AuditAction.
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Text so any kind of object id (UUID, integer, composite) fits.
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Before/after summary; never holds passwords or tokens (enforced in record()).
    summary: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    # 45 characters fit the longest IPv6 text form.
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    __table_args__ = (
        Index("ix_audit_log_occurred_at", "occurred_at"),
        Index("ix_audit_log_actor_user_id", "actor_user_id"),
        Index("ix_audit_log_action", "action"),
    )
