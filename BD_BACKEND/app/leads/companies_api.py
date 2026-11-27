"""Company record routes under /companies (empty until the M3-B tasks).

Needed so app.main already mounts this router (M3-0); the M3-B task for the company page adds
its endpoint here. Owned by workstream W2.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/companies", tags=["companies"])
