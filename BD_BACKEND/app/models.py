"""Model registry: imports every model module so all tables are on Base.metadata.

Needed because Alembic (migrations/env.py) and the schema-drift test compare the database
with Base.metadata, which only knows models that have been imported. Frozen after M1 task A0:
every module's models.py is already listed, so new models go in those files, not here.
"""

import app.audit.models  # noqa: F401
import app.campaigns.models  # noqa: F401
import app.compliance.models  # noqa: F401
import app.content.models  # noqa: F401
import app.core.models  # noqa: F401
import app.imports.models  # noqa: F401
import app.leads.models  # noqa: F401
import app.mail.models  # noqa: F401
import app.notifications.models  # noqa: F401
import app.outreach.models  # noqa: F401
