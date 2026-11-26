"""Duplicate review routes under /duplicates (empty until M2-B5).

Needed so app.main already mounts this router; M2-B5 adds the candidate list, merge and
"not a duplicate" endpoints here (REVIEW_DUPLICATES).
"""

from fastapi import APIRouter

router = APIRouter(prefix="/duplicates", tags=["duplicates"])
