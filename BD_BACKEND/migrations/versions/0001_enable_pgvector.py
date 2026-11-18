"""enable pgvector extension

Schema change: installs the PostgreSQL `vector` extension in the database. Needed because
lead and message embeddings (semantic search, planned) use the pgvector column type, and
every later migration that adds a vector column requires the extension to exist first.

Risks:
- Locking: only a brief catalog lock; there is no table to rewrite.
- Privileges: CREATE EXTENSION needs a role allowed to install it (the pgvector Docker
  image's POSTGRES_USER is). A managed database may need the extension enabled by an admin.
- Reversibility: downgrade() fails (no CASCADE, deliberately) once any column uses the
  vector type, so it cannot silently destroy embedding data. It restores nothing; a
  later re-upgrade recreates an empty extension.

Revision ID: 0001
Revises:
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Install the pgvector extension (a no-op if it is already installed)."""
    # IF NOT EXISTS keeps the migration safe on databases where the extension was
    # already installed by hand or by an administrator.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Remove the pgvector extension.

    Raises:
        sqlalchemy.exc.InternalError: If any column still uses the vector type
            (PostgreSQL refuses to drop an extension that objects depend on).
    """
    op.execute("DROP EXTENSION IF EXISTS vector")
