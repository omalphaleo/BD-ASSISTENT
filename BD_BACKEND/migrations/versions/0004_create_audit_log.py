"""create audit_log table (append-only)

Schema change: adds the `audit_log` table (actor, action, object, JSON summary, ip, time)
with three lookup indexes, plus a PL/pgSQL function and triggers that reject UPDATE, DELETE
and TRUNCATE. Needed so sensitive actions leave a history that even a bug or manual SQL
cannot alter. Mirrors app.audit.models.AuditLog; tests/test_user_model.py fails on drift.

Risks:
- Locking: creates new objects only, so nothing existing is locked or rewritten.
- (a) The triggers also block deleting audit rows in tests and during erase-person (D-099).
  A future erasure task needs a deliberate, audited approach (e.g. a reviewed migration or
  a dedicated privileged path); it cannot simply DELETE.
- (b) downgrade() destroys the entire audit history: dropping the table cannot be undone.
- Not covered: actor_user_id has no foreign key by design (audit is a leaf module).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the audit_log table, its indexes, the guard function and the two triggers."""
    # The table. occurred_at has no database default: core.clock.now() supplies it.
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        # No foreign key on purpose: nullable, and must survive any change to users.
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=True),
        sa.Column("object_id", sa.String(length=64), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # Time-range browsing, per-actor history and per-action filtering.
    op.create_index("ix_audit_log_occurred_at", "audit_log", ["occurred_at"])
    op.create_index("ix_audit_log_actor_user_id", "audit_log", ["actor_user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])

    # Guard function: any change to history raises, whatever the caller or SQL used.
    op.execute(
        """
        CREATE FUNCTION audit_log_forbid_change() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    # Row-level trigger: blocks UPDATE and DELETE of any single row.
    op.execute(
        """
        CREATE TRIGGER audit_log_forbid_update_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_forbid_change()
        """
    )
    # Statement-level trigger: TRUNCATE does not fire row triggers, so it needs its own.
    op.execute(
        """
        CREATE TRIGGER audit_log_forbid_truncate
        BEFORE TRUNCATE ON audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION audit_log_forbid_change()
        """
    )


def downgrade() -> None:
    """Drop the triggers, the guard function, the indexes and the table (deleting all history)."""
    # Triggers first: they depend on the function.
    op.execute("DROP TRIGGER audit_log_forbid_truncate ON audit_log")
    op.execute("DROP TRIGGER audit_log_forbid_update_delete ON audit_log")
    op.execute("DROP FUNCTION audit_log_forbid_change()")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_user_id", table_name="audit_log")
    op.drop_index("ix_audit_log_occurred_at", table_name="audit_log")
    op.drop_table("audit_log")
