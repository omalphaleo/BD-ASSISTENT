"""Saved segment routes under /segments (empty until M3-A4).

Needed so app.main already mounts this router (M3-0); M3-A4 adds segment create, list, edit
and delete here. Owned by workstream W1.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/segments", tags=["segments"])
