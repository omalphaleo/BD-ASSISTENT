"""add outcome and reason_code to raw_rows

Schema change: raw_rows gains two nullable columns, outcome (what the import did with the row:
imported, updated, unchanged, quarantined, possible_duplicate or rejected) and reason_code (why
a row was rejected or quarantined), plus a named CHECK on the allowed outcome values. Needed
because the import report (M2-A5, D-050) must list the specific failed and quarantined rows
with their reason, and a rejected row left no per-row record before this. Mirrors
app.imports.models.RawRow; the model tests fail if the two drift.

Risks:
- Locking: ADD COLUMN with no default is metadata-only in PostgreSQL; the CHECK is validated
  against existing rows, which is quick because the new column is NULL everywhere.
- Immutability: the raw_rows guard trigger (0007) compares only id, import_file_id, row_number,
  original_values, email_normalized and created_at, so these two columns may be updated after
  the row is stored. The original values stay untouched (D-099).
- Data: no rows are changed. Rows stored before this revision keep NULL in both columns and
  are treated as "not recorded" by the report; they never appear in the failed-rows download.
- Reversibility: downgrade() drops both columns, so every stored outcome and reason is lost and
  cannot be restored (the report totals in import_reports are kept).
- Never edit this migration after it is applied; further changes need a new migration.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors leads.contracts.RowOutcomeKind; fixed here so this migration never changes if the
# enum later grows (a new value then needs its own migration that replaces the CHECK).
OUTCOME_VALUES = (
    "imported",
    "updated",
    "unchanged",
    "quarantined",
    "possible_duplicate",
    "rejected",
)


def upgrade() -> None:
    """Add the per-row result columns and the CHECK on outcome."""
    # Nullable on purpose: existing rows have no recorded result.
    op.add_column("raw_rows", sa.Column("outcome", sa.String(length=18), nullable=True))
    op.add_column("raw_rows", sa.Column("reason_code", sa.String(length=64), nullable=True))
    allowed = ", ".join(f"'{value}'" for value in OUTCOME_VALUES)
    op.create_check_constraint("ck_raw_rows_outcome_valid", "raw_rows", f"outcome IN ({allowed})")


def downgrade() -> None:
    """Drop the result columns; the stored outcomes and reasons cannot be restored."""
    op.drop_constraint("ck_raw_rows_outcome_valid", "raw_rows", type_="check")
    op.drop_column("raw_rows", "reason_code")
    op.drop_column("raw_rows", "outcome")
