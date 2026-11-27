"""Lead record routes under /people (empty until the M3-B tasks).

Needed so app.main already mounts this router (M3-0); the M3-B tasks add the lead page, notes,
flags, owner and erase endpoints here. Owned by workstream W2.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/people", tags=["people"])
