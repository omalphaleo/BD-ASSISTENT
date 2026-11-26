"""add storage_key and size_bytes to import_files

Schema change: import_files gains two nullable columns, storage_key (where the uploaded file
is kept, as an opaque key for the storage service) and size_bytes, plus a unique constraint on
storage_key and a non-negative CHECK on size_bytes. Needed because M2-A1 stores the uploaded
bytes outside PostgreSQL (so the API and the worker can both read them) and the row must say
where. Mirrors app.imports.models.ImportFile; the model tests fail if the two drift.

Risks:
- Locking: ALTER TABLE ADD COLUMN with no default is a metadata-only change in PostgreSQL;
  the unique constraint builds an index over the current rows, which is brief on this table.
- Data: no rows are changed. Rows created before this revision keep NULL in both columns,
  meaning "no stored file"; nothing in M2 reads files for them.
- Reversibility: downgrade() drops both columns, so every stored storage_key and size is lost
  and cannot be restored. The files themselves stay on disk, orphaned, and must be removed by
  hand. Never downgrade past this revision on a database that holds real uploads.
- Numbering: this revision is 0014 and follows 0008 directly. Developer B's 0009 to 0013 are
  not on main yet; B must re-point 0009's down_revision to 0014 when they land, otherwise
  Alembic reports two heads and tests/test_migration_heads.py fails.
- Never edit this migration after it is applied; further changes need a new migration.

Revision ID: 0014
Revises: 0008
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the storage columns and their constraints to import_files."""
    # Nullable on purpose: existing rows have no stored file.
    op.add_column("import_files", sa.Column("storage_key", sa.String(length=512), nullable=True))
    op.add_column("import_files", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        "ck_import_files_size_bytes_nonnegative",
        "import_files",
        "size_bytes IS NULL OR size_bytes >= 0",
    )
    op.create_unique_constraint("uq_import_files_storage_key", "import_files", ["storage_key"])


def downgrade() -> None:
    """Drop the storage columns; the stored keys and sizes cannot be restored."""
    op.drop_constraint("uq_import_files_storage_key", "import_files", type_="unique")
    op.drop_constraint("ck_import_files_size_bytes_nonnegative", "import_files", type_="check")
    op.drop_column("import_files", "size_bytes")
    op.drop_column("import_files", "storage_key")
