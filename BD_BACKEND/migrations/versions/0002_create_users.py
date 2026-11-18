"""create users table and user_role enum

Schema change: adds the `user_role` enum (rep, manager, admin) and the `users` table with
a lowercase-email CHECK and a case-insensitive unique index on email. Needed so people can
have accounts with roles; sign-in and the permission module (planned) build on this table.
Mirrors app.core.models.User; tests/test_user_model.py fails if the two drift apart.

Risks:
- Locking: creates new objects only, so nothing existing is locked or rewritten.
- Reversibility: downgrade() drops the table, so every user row is lost and cannot be
  restored by re-upgrading. It also fails if a later table still uses `user_role`.
- Not covered: the created_at/updated_at/is_active defaults live in the application
  (core.clock.now()), so a row inserted outside the app must supply them.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False: the type is created and dropped explicitly below, so create_table
# does not try to create it a second time.
user_role = postgresql.ENUM("rep", "manager", "admin", name="user_role", create_type=False)


def upgrade() -> None:
    """Create the user_role enum, the users table and the case-insensitive email index."""
    # The enum must exist before the table that uses it. checkfirst=False makes a
    # half-applied or hand-modified database fail loudly instead of being skipped.
    user_role.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # Emails are stored lowercase; the index below then makes uniqueness case-insensitive.
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
    )
    # Unique on lower(email) so "Alice@x.com" and "alice@x.com" cannot both exist.
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)


def downgrade() -> None:
    """Drop the index, the users table (deleting all rows) and then the enum, in that order."""
    # Reverse order of upgrade(): the enum cannot be dropped while the table still uses it.
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
    user_role.drop(op.get_bind(), checkfirst=False)
