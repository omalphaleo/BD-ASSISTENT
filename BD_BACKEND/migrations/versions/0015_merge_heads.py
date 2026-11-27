"""merge the content-tables branch (0013) and the import-file-storage branch (0014)

Schema change: none. Revision 0009 (content tables, Developer B) and revision 0014 (storage_key
and size_bytes on import_files, M2-A1) were both written on top of 0008, so Alembic saw two
heads (0013 and 0014) and `alembic upgrade head` refused to run. This empty revision joins
them into one head. Decided 2026-11-26 instead of re-pointing an already merged migration,
because a database already at 0013 would otherwise skip 0014 without any error.

Risks:
- Locking and data: none; upgrade() and downgrade() do nothing.
- Order: the two branches touch different tables (the content, campaigns, outreach, mail and
  notifications tables versus two columns of import_files), so it does not matter which one
  runs first. A database at 0008 applies both; at 0013 it applies 0014; at 0014 it applies
  0009 to 0013.
- Reversibility: downgrading this revision returns to both parents; each parent's own
  downgrade() then decides what is lost (see 0009 and 0014).
- Never edit this migration after it is applied. New migrations continue from 0015 (0016 next).

Revision ID: 0015
Revises: 0013, 0014
Create Date: 2026-11-26
"""

from collections.abc import Sequence

revision: str = "0015"
down_revision: str | Sequence[str] | None = ("0013", "0014")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: this revision only joins two migration branches."""


def downgrade() -> None:
    """Nothing to change: each parent revision undoes its own schema change."""
