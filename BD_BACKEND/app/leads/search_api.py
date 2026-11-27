"""Lead search routes under /search (empty until M3-A2).

Needed so app.main already mounts this router (M3-0); M3-A2 adds the search endpoints here,
so no feature task edits main.py. Owned by workstream W1.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/search", tags=["search"])
