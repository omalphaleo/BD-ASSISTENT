"""Quarantine routes under /quarantine (empty until M2-B2).

Needed so app.main already mounts this router; M2-B2 adds the list, fix, release and discard
endpoints here, each declaring its permission.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/quarantine", tags=["quarantine"])
