"""create settings, clock_offsets and job_locks tables

Schema change: adds three `core` tables. `settings` is a key/JSONB-value store with a
version and the last editor; `clock_offsets` holds at most one row, the admin test-clock
offset; `job_locks` holds named application-level locks with an owner and an expiry.
Needed so later milestones can read admin settings (M2 import lists, M5 limits), store the
test-clock offset and coordinate workers (mailbox polling) without another migration.
Mirrors app.core.models.Setting, ClockOffset and JobLock; tests/test_user_model.py fails if
the models and this schema drift apart. Decisions: docs/decisions/0002-2026-11-19-*.md.

Risks:
- Locking: creates new objects only (plus foreign keys to users, which only read users), so
  nothing existing is locked or rewritten.
- No data is inserted: no default settings and no clock_offsets row (no row means offset 0).
- Reversibility: downgrade() drops the three tables, so every stored setting, the clock
  offset and any held lock is lost and cannot be restored. users is untouched.
- Not covered: created_at, updated_at and locked_at have no database default (core.clock.now()
  supplies them in the app), so a row inserted outside the app must supply them.
- Never edit this migration after it is applied; further changes need a new migration.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create settings, clock_offsets and job_locks with their constraints and one index."""
    # Admin-editable configuration, one row per key.
    op.create_table(
        "settings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        # JSONB so one column holds a string, number, boolean or list.
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # SET NULL: deleting a user keeps the setting and only clears who last changed it.
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name="fk_settings_updated_by_users", ondelete="SET NULL"
        ),
        # One row per key; also serves the lookup by key.
        sa.UniqueConstraint("key", name="uq_settings_key"),
        # Lowercase letters, digits, underscores and dots only; rejects uppercase, spaces,
        # other symbols and the empty string.
        sa.CheckConstraint("key ~ '^[a-z0-9_.]+$'", name="ck_settings_key_format"),
        sa.CheckConstraint("version >= 1", name="ck_settings_version_positive"),
    )

    # The admin test-clock offset. No row is inserted: no row means an offset of zero.
    op.create_table(
        "clock_offsets",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("singleton", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        # Signed seconds; negative moves the clock back.
        sa.Column("offset_seconds", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name="fk_clock_offsets_updated_by_users",
            ondelete="SET NULL",
        ),
        # singleton must be true and unique, so the table can never hold more than one row.
        sa.CheckConstraint("singleton", name="ck_clock_offsets_singleton"),
        sa.UniqueConstraint("singleton", name="uq_clock_offsets_singleton"),
    )

    # Named application-level locks; a row exists only while the lock is held.
    op.create_table(
        "job_locks",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("locked_by", sa.String(length=128), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # Only one worker can hold a given lock name.
        sa.UniqueConstraint("name", name="uq_job_locks_name"),
        # A lock must expire after it was taken, so a crashed worker's lock can be reclaimed.
        sa.CheckConstraint("expires_at > locked_at", name="ck_job_locks_expires_after_locked"),
    )
    # Finds expired locks to reclaim.
    op.create_index("ix_job_locks_expires_at", "job_locks", ["expires_at"])


def downgrade() -> None:
    """Drop the index and the three tables (deleting all settings, the offset and locks)."""
    # Reverse order of upgrade(). Dropping a table also removes its FK and CHECKs.
    op.drop_index("ix_job_locks_expires_at", table_name="job_locks")
    op.drop_table("job_locks")
    op.drop_table("clock_offsets")
    op.drop_table("settings")
