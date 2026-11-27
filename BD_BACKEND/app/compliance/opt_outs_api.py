"""Opt-out routes under /opt-outs (empty until the M3-B tasks).

Needed so app.main already mounts this router (M3-0); the M3-B opt-out tasks add list, add and
remove here. Owned by workstream W2.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/opt-outs", tags=["opt-outs"])
