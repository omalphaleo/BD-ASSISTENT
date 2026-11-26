"""Industry and state mapping routes under /reference-mappings (empty until M2-B6).

Needed so app.main already mounts this router; M2-B6 adds the list and edit endpoints here
(MANAGE_SOURCE_PROFILES, D-076).
"""

from fastapi import APIRouter

router = APIRouter(prefix="/reference-mappings", tags=["reference-mappings"])
