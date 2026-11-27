"""Tests for POST /imports/{id}/start and GET /imports/{id}/progress (M2-A3) on real PostgreSQL.

Needed because the start step guards the pipeline: only the uploader may start, once, with a
saved mapping that covers the mandatory fields (D-069); the job is queued after the state change
is committed and a second queued job is refused; progress is visible like the status call. The
queue is replaced by a recording fake, so no worker or Procrastinate connection is needed.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from csrf_client import CsrfTestClient
from factories.core import make_user
from fastapi import FastAPI
from fastapi.testclient import TestClient
from import_files import csv_bytes
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.audit.services import AuditAction
from app.config import get_settings
from app.core import services
from app.core.models import User, UserRole
from app.db import get_session
from app.imports.api import get_import_queue
from app.imports.models import ImportFile, ImportReport, ImportStatus
from app.imports.storage import LocalDiskStorage, get_file_storage
from app.main import app as real_app

ROWS = [["First Name", "Email"], ["Ada", "ada@example.com"], ["Alan", "alan@example.com"]]
FULL_MAPPING = {0: "first_name", 1: "email"}


class RecordingQueue:
    """Stands in for the Procrastinate defer: records import IDs, can pretend one is queued."""

    def __init__(self) -> None:
        self.queued: list[uuid.UUID] = []
        self.refuse = False

    def __call__(self, import_id: uuid.UUID) -> bool:
        """Record the call; return False (already queued) when told to refuse."""
        self.queued.append(import_id)
        return not self.refuse


@pytest.fixture
def queue() -> RecordingQueue:
    """The fake job queue shared by the app and the test."""
    return RecordingQueue()


@pytest.fixture
def app(db_session: Session, tmp_path: Path, queue: RecordingQueue) -> Iterator[FastAPI]:
    """The real app wired to the test session, a temporary upload directory and the fake queue."""

    def session_override() -> Iterator[Session]:
        yield db_session

    real_app.dependency_overrides[get_session] = session_override
    real_app.dependency_overrides[get_file_storage] = lambda: LocalDiskStorage(tmp_path / "up")
    real_app.dependency_overrides[get_import_queue] = lambda: queue
    yield real_app
    real_app.dependency_overrides.clear()


def _client(session: Session, app: FastAPI, user: User) -> TestClient:
    """A client signed in as the user through a real session cookie."""
    client = CsrfTestClient(app)
    token, _ = services.create_session(session, user)
    client.cookies.set(get_settings().session_cookie_name, token)
    return client


def _upload_and_map(client: TestClient, mapping: dict[int, str | None]) -> uuid.UUID:
    """Upload the sample CSV and save the given mapping; return the import ID."""
    response = client.post(
        "/imports/upload", files={"file": ("l.csv", csv_bytes(ROWS), "application/octet-stream")}
    )
    assert response.status_code == 201, response.text
    import_id = uuid.UUID(response.json()["id"])
    body = {"columns": [{"column_index": i, "target_field": t} for i, t in mapping.items()]}
    assert client.put(f"/imports/{import_id}/mapping", json=body).status_code == 200
    return import_id


@pytest.fixture
def rep(db_session: Session) -> User:
    """The uploader."""
    return make_user(db_session)


@pytest.fixture
def rep_client(db_session: Session, app: FastAPI, rep: User) -> TestClient:
    """A client signed in as the uploader."""
    return _client(db_session, app, rep)


def test_start_sets_processing_queues_the_job_and_audits(
    db_session: Session, rep_client: TestClient, queue: RecordingQueue
) -> None:
    """A valid start answers 202, commits PROCESSING, creates the report and queues one job."""
    import_id = _upload_and_map(rep_client, FULL_MAPPING)

    response = rep_client.post(f"/imports/{import_id}/start")

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "processing"
    assert queue.queued == [import_id]
    assert db_session.get(ImportFile, import_id).status is ImportStatus.PROCESSING
    assert db_session.scalars(select(ImportReport)).one().received == 0
    actions = [
        r.action for r in db_session.scalars(select(AuditLog).order_by(AuditLog.occurred_at))
    ]
    assert AuditAction.IMPORT_STARTED.value in actions


def test_start_without_a_required_field_mapped_is_refused(
    rep_client: TestClient, queue: RecordingQueue
) -> None:
    """Email unmapped (D-069): 409 mapping_incomplete and nothing is queued."""
    import_id = _upload_and_map(rep_client, {0: "first_name", 1: None})

    response = rep_client.post(f"/imports/{import_id}/start")

    assert response.status_code == 409
    assert response.json()["code"] == "mapping_incomplete"
    assert queue.queued == []


def test_start_without_a_saved_mapping_is_refused(
    rep_client: TestClient, queue: RecordingQueue
) -> None:
    """No mapping saved yet: 409 mapping_incomplete."""
    response = rep_client.post(
        "/imports/upload", files={"file": ("l.csv", csv_bytes(ROWS), "application/octet-stream")}
    )
    import_id = response.json()["id"]

    refused = rep_client.post(f"/imports/{import_id}/start")

    assert refused.status_code == 409
    assert refused.json()["code"] == "mapping_incomplete"
    assert queue.queued == []


def test_starting_twice_is_refused_as_already_processing(
    rep_client: TestClient, queue: RecordingQueue
) -> None:
    """The second start finds PROCESSING: 409 already_processing, no second job."""
    import_id = _upload_and_map(rep_client, FULL_MAPPING)
    assert rep_client.post(f"/imports/{import_id}/start").status_code == 202

    second = rep_client.post(f"/imports/{import_id}/start")

    assert second.status_code == 409
    assert second.json()["code"] == "already_processing"
    assert len(queue.queued) == 1


def test_a_job_already_in_the_queue_is_refused(
    rep_client: TestClient, queue: RecordingQueue
) -> None:
    """The queueing lock refuses the job (queue returns False): 409 already_processing."""
    queue.refuse = True
    import_id = _upload_and_map(rep_client, FULL_MAPPING)

    response = rep_client.post(f"/imports/{import_id}/start")

    assert response.status_code == 409
    assert response.json()["code"] == "already_processing"


def test_only_the_uploader_may_start(
    db_session: Session, app: FastAPI, rep_client: TestClient, queue: RecordingQueue
) -> None:
    """A manager can see the import but cannot start it: 409 not_startable, nothing queued."""
    import_id = _upload_and_map(rep_client, FULL_MAPPING)
    manager = make_user(db_session, role=UserRole.MANAGER)

    response = _client(db_session, app, manager).post(f"/imports/{import_id}/start")

    assert response.status_code == 409
    assert response.json()["code"] == "not_startable"
    assert queue.queued == []


def test_a_hidden_import_looks_missing(
    db_session: Session, app: FastAPI, rep_client: TestClient, queue: RecordingQueue
) -> None:
    """Another rep gets 404 for both start and progress of someone else's import."""
    import_id = _upload_and_map(rep_client, FULL_MAPPING)
    stranger = _client(db_session, app, make_user(db_session))

    assert stranger.post(f"/imports/{import_id}/start").status_code == 404
    assert stranger.get(f"/imports/{import_id}/progress").status_code == 404
    assert queue.queued == []


def test_progress_reads_zero_before_start_and_the_counters_after(
    db_session: Session, rep_client: TestClient
) -> None:
    """Progress is all zeros before the start; with a report it shows counters and percent."""
    import_id = _upload_and_map(rep_client, FULL_MAPPING)
    before = rep_client.get(f"/imports/{import_id}/progress").json()
    assert (before["received"], before["percent"], before["finished"]) == (0, 0, False)

    rep_client.post(f"/imports/{import_id}/start")
    report = db_session.scalars(select(ImportReport)).one()
    report.received, report.imported = 1, 1
    db_session.flush()

    after = rep_client.get(f"/imports/{import_id}/progress").json()
    assert (after["status"], after["received"], after["imported"]) == ("processing", 1, 1)
    assert after["percent"] == 50  # one of the two data rows
    assert after["finished"] is False


def test_progress_requires_login(app: FastAPI) -> None:
    """Without a session progress gives 401; start is refused (401, or 403 from CSRF)."""
    client = CsrfTestClient(app)
    missing = uuid.uuid4()

    assert client.get(f"/imports/{missing}/progress").status_code == 401
    assert client.post(f"/imports/{missing}/start").status_code in (401, 403)
