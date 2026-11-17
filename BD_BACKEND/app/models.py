"""Model registry: imports every model module so all tables are on Base.metadata.

Needed because Alembic (migrations/env.py) and the schema-drift test compare the database
with Base.metadata, which only knows models that have been imported; add new model modules here.
"""

import app.audit.models  # noqa: F401
import app.core.models  # noqa: F401
