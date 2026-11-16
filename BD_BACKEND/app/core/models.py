"""Core data models: application users, their roles and their sign-in sessions.

Needed as the persisted identity for sign-in and permissions; Alembic reads these tables
through Base.metadata (migrations/env.py), and migrations 0002 (users) and 0003 (sessions)
create the same schema. Session creation and checking (planned) will build on UserSession.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import now
from app.db import Base


class UserRole(enum.StrEnum):
    """Roles a user can hold; the lowercase value is what PostgreSQL stores."""

    REP = "rep"
    MANAGER = "manager"
    ADMIN = "admin"


class User(Base):
    """A person who can sign in. Emails are unique case-insensitively and stored lowercase."""

    __tablename__ = "users"  # "user" is a reserved word in PostgreSQL

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Time comes only from core.clock.now(), so no server-side defaults.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now, onupdate=now
    )

    __table_args__ = (
        # Two layers keep emails case-insensitive: the CHECK forces lowercase storage and
        # the unique index on lower(email) blocks duplicates that differ only by case.
        CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )


class UserSession(Base):
    """A server-side sign-in session; only the SHA-256 hash of its token is stored.

    Named UserSession to avoid clashing with SQLAlchemy's Session. A session is active
    while revoked_at is NULL and expires_at is in the future; the service (planned) sets both.
    """

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    # Explicit FK name: the project has no naming convention, so this keeps the name stable.
    # CASCADE: deleting a user also removes their sessions.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_sessions_user_id_users"),
        nullable=False,
    )
    # Hex digest of the session token; the raw token is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Time comes only from core.clock.now(), so no server-side defaults.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )
    # No default: the session service decides the lifetime.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # NULL means the session has not been revoked.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("uq_sessions_token_hash", "token_hash", unique=True),
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_expires_at", "expires_at"),
        CheckConstraint("expires_at > created_at", name="ck_sessions_expires_after_created"),
        CheckConstraint("char_length(token_hash) = 64", name="ck_sessions_token_hash_length"),
    )
