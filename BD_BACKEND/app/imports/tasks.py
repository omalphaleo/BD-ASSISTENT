"""Procrastinate tasks of the imports module: process_import (M2-A3).

Needed so a started import runs in the worker, not in the request. The task is a thin wrapper
around imports.pipeline.run_import; app.worker already lists this module in import_paths. One
job may wait in the queue per import (queueing lock on the import ID), and the pipeline's
state checks and resume cursor make a repeated run safe (plan section 8).
"""

import asyncio
import logging
import uuid

from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import get_engine
from app.imports.parsers import limits_from_settings
from app.imports.pipeline import run_import
from app.imports.storage import get_file_storage
from app.imports.wiring import get_ingest_row
from app.worker import app

logger = logging.getLogger(__name__)

PROCESS_IMPORT_TASK_NAME = "imports.process_import"


def queueing_lock_for(import_id: uuid.UUID) -> str:
    """The queueing lock that allows one waiting process_import job per import."""
    return f"import:{import_id}"


@app.task(name=PROCESS_IMPORT_TASK_NAME)
def process_import(import_id: str) -> None:
    """Thin wrapper: open a session and run the import pipeline (no lead data is logged)."""
    settings = get_settings()
    # expire_on_commit=False: the pipeline commits after every chunk and keeps using objects.
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        run_import(
            session,
            uuid.UUID(import_id),
            storage=get_file_storage(),
            limits=limits_from_settings(settings),
            ingest_row=get_ingest_row(),
        )
    logger.info("process_import finished import_id=%s", import_id)


async def defer_process_import(import_id: uuid.UUID) -> bool:
    """Queue the job for one import.

    Returns:
        True if queued, False if a job for this import is already waiting.
    """
    async with app.open_async():
        try:
            await process_import.configure(queueing_lock=queueing_lock_for(import_id)).defer_async(
                import_id=str(import_id)
            )
        except AlreadyEnqueued:
            return False
    return True


def queue_import(import_id: uuid.UUID) -> bool:
    """Queue the job from synchronous code (a route handler running in a worker thread)."""
    return asyncio.run(defer_process_import(import_id))
