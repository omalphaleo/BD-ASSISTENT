"""Source profile routes under /source-profiles (empty until M2-A6).

Needed so app.main already mounts this router; M2-A6 adds the list, create and edit
endpoints here (MANAGE_SOURCE_PROFILES), kept apart from /imports to match the admin page.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/source-profiles", tags=["source-profiles"])
