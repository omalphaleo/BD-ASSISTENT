"""Core data models: users, sign-in sessions, the settings store, the test-clock offset, job locks.

Needed as the persisted identity for sign-in and permissions, plus the shared configuration
and coordination tables later milestones build on. Alembic reads these tables through
Base.metadata (migrations/env.py); migrations 0002 (users), 0003 (sessions) and 0005
(settings, clock_offsets, job_locks) create the same schema. Setting, ClockOffset and JobLock
are tables only in M1 task A2: no service reads or writes them yet (decision record 0002).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
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


class Setting(Base):
    """One admin-editable configuration value, looked up by its unique key.

    Holds sending limits, AI model names, feature flags and the personal-email-domain and
    generic-prefix lists (decision record 0002). Which keys exist, and the shape of each
    value, is decided by the settings service (planned), not by the schema, so a new setting
    needs no migration. No rows are seeded in A2.
    """

    __tablename__ = "settings"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    # Lowercase letters, digits, underscores and dots, e.g. "email.blocked_domains"; the
    # CHECK keeps keys uniform so lookups never depend on casing or stray characters.
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    # JSONB so one column holds a string, number, boolean or list (the email lists).
    value: Mapped[object] = mapped_column(JSONB, nullable=False)
    # Starts at 1; the settings service (planned) increments it on every change.
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    # Time comes only from core.clock.now(), so no server-side defaults.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now, onupdate=now
    )
    # Last user who changed the value. SET NULL keeps the setting if that user is deleted;
    # the audit log (planned writes) holds the full history.
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_settings_updated_by_users"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("key", name="uq_settings_key"),
        CheckConstraint("key ~ '^[a-z0-9_.]+$'", name="ck_settings_key_format"),
        CheckConstraint("version >= 1", name="ck_settings_version_positive"),
    )


class ClockOffset(Base):
    """The admin test-clock offset, stored as at most one row.

    Table only in A2: core.clock keeps its in-memory offset and does not read this table
    yet. A missing row means an offset of zero; the first row appears when an admin first
    changes the offset. Changing it while real sending is active is blocked, and it must be
    zero before real sending is activated (decision record 0002; enforced in a later service).
    """

    __tablename__ = "clock_offsets"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    # Always true. With the unique constraint below it caps the table at one row.
    singleton: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # Signed seconds added to the real time; negative moves the clock back.
    offset_seconds: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    # Time comes only from core.clock.now(), so no server-side defaults.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now, onupdate=now
    )
    # Last admin who changed the offset; SET NULL keeps the row if that user is deleted.
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_clock_offsets_updated_by_users"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint("singleton", name="ck_clock_offsets_singleton"),
        UniqueConstraint("singleton", name="uq_clock_offsets_singleton"),
    )


class JobLock(Base):
    """An application-level lock held by one worker for a named piece of work.

    Used only for coordination Procrastinate does not cover, such as stopping two workers
    polling the same mailbox at once (decision record 0002). A row exists only while the
    lock is held: acquiring inserts it, releasing deletes it. expires_at lets a lock left by
    a crashed worker be reclaimed. Acquire and release logic is planned, not part of A2.
    """

    __tablename__ = "job_locks"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    # What is locked, e.g. "poll_mailbox:<mailbox_id>"; unique so only one worker holds it.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Identifier of the worker holding the lock.
    locked_by: Mapped[str] = mapped_column(String(128), nullable=False)
    # Time comes only from core.clock.now(), so no server-side defaults.
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )
    # No default: the code that takes the lock chooses how long it may hold it.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("name", name="uq_job_locks_name"),
        Index("ix_job_locks_expires_at", "expires_at"),
        CheckConstraint("expires_at > locked_at", name="ck_job_locks_expires_after_locked"),
    )
