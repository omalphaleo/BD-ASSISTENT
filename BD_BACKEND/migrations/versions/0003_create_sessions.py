"""create sessions table

Schema change: adds the `sessions` table (user_id FK, SHA-256 token hash, created/expires/
revoked timestamps) with a unique index on token_hash, lookup indexes on user_id and
expires_at, and two CHECK constraints. Needed so sign-in can be stored server-side and
revoked; the session service (planned) builds on this table.
Mirrors app.core.models.UserSession; tests/test_user_model.py fails if the two drift apart.

Risks:
- Locking: creates new objects only, so nothing existing is locked or rewritten.
- Reversibility: downgrade() drops the table, so every session row is lost (everyone is
  logged out). Nothing else is lost: users are untouched.
- Not covered: created_at has no database default (core.clock.now() supplies it in the app),
  so a row inserted outside the app must supply it.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the sessions table, its indexes and its CHECK constraints."""
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        # SHA-256 hex digest of the session token; the raw token is never stored.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # NULL means the session is still active.
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # CASCADE: deleting a user removes their sessions with them.
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_sessions_user_id_users", ondelete="CASCADE"
        ),
        # A session must expire after it was created.
        sa.CheckConstraint("expires_at > created_at", name="ck_sessions_expires_after_created"),
        # Guards against storing a raw token or truncated value instead of a SHA-256 hex digest.
        sa.CheckConstraint("char_length(token_hash) = 64", name="ck_sessions_token_hash_length"),
    )
    # Unique: each token hash identifies exactly one session; also serves the login lookup.
    op.create_index("uq_sessions_token_hash", "sessions", ["token_hash"], unique=True)
    # Finds all sessions of a user (revoke-all, listing).
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    # Supports cleanup of expired sessions.
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])


def downgrade() -> None:
    """Drop the three indexes and then the sessions table (deleting all sessions)."""
    # Reverse order of upgrade(). Dropping the table also removes its FK and CHECKs.
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_index("uq_sessions_token_hash", table_name="sessions")
    op.drop_table("sessions")
