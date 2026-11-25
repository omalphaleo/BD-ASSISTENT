"""Procrastinate tasks owned by the core module, starting with the worker sample job.

Needed to prove the PostgreSQL job queue works end to end (M1 acceptance, demo step "run sample
job") and to give later tasks.py files one pattern to copy: a thin task that only calls a
service, plus a queueing lock so the same job is never queued twice.

Defer it by hand with:  python -m app.core.tasks
"""

import asyncio
import logging
import sys

from procrastinate.exceptions import AlreadyEnqueued

from app.core.services import run_sample_job
from app.worker import app

logger = logging.getLogger(__name__)

SAMPLE_JOB_NAME = "core.sample_job"
# One sample job may wait in the queue at a time; a second defer is refused (plan.md section 8).
SAMPLE_JOB_QUEUEING_LOCK = "core.sample_job"
SAMPLE_JOB_MESSAGE = "hello from the worker"


@app.task(name=SAMPLE_JOB_NAME, queueing_lock=SAMPLE_JOB_QUEUEING_LOCK)
def sample_job(message: str) -> None:
    """Thin wrapper: run the sample service and log one structured line (no lead data)."""
    result = run_sample_job(message)
    logger.info("sample_job done echoed_message=%s", result.echoed_message)


async def defer_sample_job() -> bool:
    """Queue one sample job.

    Returns:
        True if queued, False if one is already waiting (the queueing lock refused it).
    """
    async with app.open_async():
        try:
            await sample_job.defer_async(message=SAMPLE_JOB_MESSAGE)
        except AlreadyEnqueued:
            return False
    return True


def main() -> int:
    """Command-line entry for `python -m app.core.tasks`; returns the process exit code."""
    if asyncio.run(defer_sample_job()):
        print("sample job queued")
    else:
        print("sample job already waiting in the queue; not queued again")
    return 0


if __name__ == "__main__":
    sys.exit(main())
