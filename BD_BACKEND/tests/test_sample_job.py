"""Tests for the A10 worker sample job (service, task registration and queueing lock).

Needed so the "worker runs a sample job" acceptance rule is checked automatically; the job
touches no tables and no network, so it runs on Procrastinate's in-memory connector instead
of PostgreSQL. Later tasks.py tests can copy this shape.
"""

import asyncio
import logging

import pytest
from procrastinate.exceptions import AlreadyEnqueued
from procrastinate.testing import InMemoryConnector

from app.core.services import SampleJobResult, run_sample_job
from app.core.tasks import (
    SAMPLE_JOB_MESSAGE,
    SAMPLE_JOB_NAME,
    defer_sample_job,
    sample_job,
)
from app.worker import app


def test_service_is_idempotent() -> None:
    """Calling the service twice with the same message returns equal results."""
    assert run_sample_job("hi") == run_sample_job("hi") == SampleJobResult(echoed_message="hi")


def test_task_is_registered_with_the_worker() -> None:
    """The sample task is known to the worker app under its stable name."""
    assert SAMPLE_JOB_NAME in app.tasks


def test_deferred_job_runs_to_success(caplog: pytest.LogCaptureFixture) -> None:
    """A deferred job is picked up by the worker, succeeds and logs the echoed message."""
    connector = InMemoryConnector()
    with app.replace_connector(connector) as test_app:

        async def scenario() -> None:
            await sample_job.defer_async(message=SAMPLE_JOB_MESSAGE)
            await test_app.run_worker_async(wait=False)

        with caplog.at_level(logging.INFO, logger="app.core.tasks"):
            asyncio.run(scenario())

    (job,) = connector.jobs.values()
    assert job["status"] == "succeeded"
    assert SAMPLE_JOB_MESSAGE in caplog.text


def test_second_defer_while_waiting_is_refused() -> None:
    """The queueing lock refuses a second identical job while the first is still queued."""
    with app.replace_connector(InMemoryConnector()):

        async def scenario() -> None:
            await sample_job.defer_async(message=SAMPLE_JOB_MESSAGE)
            await sample_job.defer_async(message=SAMPLE_JOB_MESSAGE)

        with pytest.raises(AlreadyEnqueued):
            asyncio.run(scenario())


def test_defer_helper_reports_queued_then_refused() -> None:
    """defer_sample_job returns True the first time and False while one is already waiting."""
    with app.replace_connector(InMemoryConnector()):
        assert asyncio.run(defer_sample_job()) is True
        assert asyncio.run(defer_sample_job()) is False
