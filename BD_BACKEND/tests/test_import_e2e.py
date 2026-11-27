"""End-to-end import journey (M2-A7): upload, map, start, process, report, assign, download.

Needed because every earlier import test uses a fake ingest_row or factory-built rows. Here the
whole W1 flow runs through the real HTTP routes and the pipeline runs with the REAL ingest_row
from imports.wiring (integration step I1), so W1's counters, report, change summary, downloads
and owner assignment are checked against what W2's validation, quarantine, matching and merge
really produce. Only the job queue is replaced (a recording fake; the test then runs the job's
function directly) and the upload directory is a temp folder. All data is synthetic.
"""

import csv
import io
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
from app.imports.models import ImportStatus, RawRow
from app.imports.parsers import limits_from_settings
from app.imports.pipeline import run_import
from app.imports.storage import LocalDiskStorage, get_file_storage
from app.imports.wiring import get_ingest_row
from app.leads.models import (
    DuplicateCandidate,
    Person,
    PersonEmail,
    QuarantineRecord,
)
from app.main import app as real_app

HEADER = ["First Name", "Last Name", "Email", "Title", "Owner"]
# Column index to target field, as the mapping step saves it.
MAPPING = {0: "first_name", 1: "last_name", 2: "email", 3: "title", 4: "owner_name"}
# Each row is chosen to hit one real W2 outcome (row numbers count the header as row 1).
ROWS = [
    HEADER,
    ["Ada", "Lovelace", "ada@acme-widgets.com", "Engineer", "Zed Smith"],  # 2: new lead
    ["Alan", "Turing", "alan@acme-widgets.com", "Analyst", ""],  # 3: new lead
    ["", "=1+1", "grace@acme-widgets.com", "Admiral", ""],  # 4: no first name -> quarantine
    ["Pat", "Personal", "pat@gmail.com", "Tester", ""],  # 5: only a personal email -> quarantine
    ["Ada", "Lovelace", "ada@acme-widgets.com", "Senior Engineer", ""],  # 6: same email -> update
    ["Ada", "Lovelace", "ada.l@acme-widgets.com", "Engineer", ""],  # 7: same name+domain -> flag
]


class RecordingQueue:
    """Stands in for the Procrastinate defer: records the queued import IDs."""

    def __init__(self) -> None:
        self.queued: list[uuid.UUID] = []

    def __call__(self, import_id: uuid.UUID) -> bool:
        """Record the call and report the job as newly queued."""
        self.queued.append(import_id)
        return True


@pytest.fixture
def queue() -> RecordingQueue:
    """The fake job queue shared by the app and the test."""
    return RecordingQueue()


@pytest.fixture
def storage(tmp_path: Path) -> LocalDiskStorage:
    """A throwaway upload directory shared by the API and the job."""
    return LocalDiskStorage(tmp_path / "uploads")


@pytest.fixture
def app(db_session: Session, storage: LocalDiskStorage, queue: RecordingQueue) -> Iterator[FastAPI]:
    """The real app wired to the test session, the temp storage and the fake queue."""

    def session_override() -> Iterator[Session]:
        yield db_session

    real_app.dependency_overrides[get_session] = session_override
    real_app.dependency_overrides[get_file_storage] = lambda: storage
    real_app.dependency_overrides[get_import_queue] = lambda: queue
    yield real_app
    real_app.dependency_overrides.clear()


def _client(db: Session, app: FastAPI, user: User) -> TestClient:
    """A client signed in as the user through a real session cookie."""
    client = CsrfTestClient(app)
    token, _ = services.create_session(db, user)
    client.cookies.set(get_settings().session_cookie_name, token)
    return client


@pytest.fixture
def rep(db_session: Session) -> User:
    """The uploader (a rep: sees only their own imports)."""
    return make_user(db_session)


@pytest.fixture
def manager(db_session: Session) -> User:
    """A manager: may assign leads and sees every import."""
    return make_user(db_session, role=UserRole.MANAGER)


@pytest.fixture
def rep_client(db_session: Session, app: FastAPI, rep: User) -> TestClient:
    """A client signed in as the uploader."""
    return _client(db_session, app, rep)


def _upload(client: TestClient, rows: list[list[str]], **form: str) -> object:
    """POST the rows as a CSV upload and return the response."""
    return client.post(
        "/imports/upload",
        files={"file": ("leads.csv", csv_bytes(rows), "application/octet-stream")},
        data=form,
    )


def _run_import_job(db: Session, storage: LocalDiskStorage, import_id: uuid.UUID) -> None:
    """Do what the worker does for process_import, with the REAL ingest_row from the wiring."""
    run_import(
        db,
        import_id,
        storage=storage,
        limits=limits_from_settings(get_settings()),
        ingest_row=get_ingest_row(),
    )


@pytest.fixture
def finished_import(
    db_session: Session, rep_client: TestClient, storage: LocalDiskStorage, queue: RecordingQueue
) -> uuid.UUID:
    """Upload, map and start the sample file, then run the job; returns the import ID."""
    response = _upload(rep_client, ROWS)
    assert response.status_code == 201, response.text
    import_id = uuid.UUID(response.json()["id"])
    body = {"columns": [{"column_index": i, "target_field": t} for i, t in MAPPING.items()]}
    assert rep_client.put(f"/imports/{import_id}/mapping", json=body).status_code == 200
    assert rep_client.post(f"/imports/{import_id}/start").status_code == 202
    assert queue.queued == [import_id]
    _run_import_job(db_session, storage, import_id)
    db_session.expire_all()
    return import_id


def test_the_real_ingest_row_outcomes_land_in_the_report(
    rep_client: TestClient, finished_import: uuid.UUID
) -> None:
    """Six rows: 2 imported, 1 updated, 1 possible duplicate, 2 quarantined; import COMPLETED."""
    progress = rep_client.get(f"/imports/{finished_import}/progress").json()
    report = rep_client.get(f"/imports/{finished_import}/report").json()

    assert progress["status"] == "completed"
    assert (
        report["received"],
        report["imported"],
        report["updated"],
        report["unchanged"],
        report["duplicates_found"],
        report["quarantined"],
        report["rejected"],
    ) == (6, 2, 1, 0, 1, 2, 0)
    assert report["changes_total"] == 1


def test_leads_quarantine_and_the_duplicate_flag_exist_in_the_database(
    db_session: Session, finished_import: uuid.UUID
) -> None:
    """W2's writes are real: merged title, one email per person, two quarantined, one flag."""
    ada = db_session.scalars(
        select(Person)
        .join(PersonEmail, PersonEmail.person_id == Person.id)
        .where(PersonEmail.address == "ada@acme-widgets.com")
    ).one()
    people = db_session.scalars(select(Person)).all()
    raw_rows = db_session.scalars(select(RawRow).where(RawRow.import_file_id == finished_import))

    assert ada.title == "Senior Engineer"  # the later row won (latest values only, D-008)
    assert len(people) == 3  # Ada, Alan and the flagged second "Ada" (kept separate, D-092)
    assert len(db_session.scalars(select(QuarantineRecord)).all()) == 2
    assert len(db_session.scalars(select(DuplicateCandidate)).all()) == 1
    assert len(raw_rows.all()) == 6  # every original row stored untouched (D-099)


def test_the_change_summary_shows_the_real_field_change(
    rep_client: TestClient, finished_import: uuid.UUID
) -> None:
    """The updated lead's changes list carries the title change W2's merge produced."""
    page = rep_client.get(f"/imports/{finished_import}/changes").json()

    assert page["total"] == 1
    [item] = page["items"]
    assert item["name"] == "Ada Lovelace"
    assert [(c["field"], c["old"], c["new"]) for c in item["changes"]] == [
        ("title", "Engineer", "Senior Engineer")
    ]

    csv_text = rep_client.get(f"/imports/{finished_import}/download/changes.csv").text
    assert "Senior Engineer" in csv_text


def test_the_failed_rows_download_lists_quarantined_rows_and_neutralises_formulas(
    db_session: Session, rep_client: TestClient, finished_import: uuid.UUID
) -> None:
    """Both quarantined rows are listed with their reason; a cell starting with = is defused."""
    response = rep_client.get(f"/imports/{finished_import}/download/failed-rows.csv")

    rows = list(csv.reader(io.StringIO(response.text)))
    assert response.status_code == 200
    assert len(rows) == 3  # header plus the two quarantined rows
    assert "'=1+1" in response.text  # formula injection neutralised (CLAUDE.md)
    assert "=1+1" not in response.text.replace("'=1+1", "")
    audit = db_session.scalars(
        select(AuditLog).where(AuditLog.action == AuditAction.IMPORT_REPORT_DOWNLOADED.value)
    ).all()
    assert len(audit) == 1


def test_the_job_audited_start_and_finish_without_lead_data(
    db_session: Session, finished_import: uuid.UUID
) -> None:
    """import.started and import.finished are recorded and no audit row holds an email."""
    rows = db_session.scalars(select(AuditLog)).all()
    actions = {row.action for row in rows}

    assert {AuditAction.IMPORT_STARTED.value, AuditAction.IMPORT_FINISHED.value} <= actions
    assert all("@" not in str(row.summary) for row in rows if row.summary)


def test_a_manager_assigns_the_leads_whose_owner_matched_no_user(
    db_session: Session, app: FastAPI, manager: User, finished_import: uuid.UUID
) -> None:
    """ "Zed Smith" matched nobody: the manager assigns that group and the lead gets the owner."""
    client = _client(db_session, app, manager)
    target = make_user(db_session, email="target@example.com")

    groups = client.get(f"/imports/{finished_import}/unmatched-owners").json()
    assigned = client.post(
        f"/imports/{finished_import}/assign-owner",
        json={"owner_group": "zed smith", "user_id": str(target.id)},
    )

    assert "zed smith" in [group["owner_group"] for group in groups]
    assert assigned.json() == {"assigned": 1, "skipped": 0}
    db_session.expire_all()
    owned = db_session.scalars(select(Person).where(Person.owner_id == target.id)).all()
    assert [person.first_name for person in owned] == ["Ada"]  # the only row that named Zed Smith


def test_a_rep_cannot_assign_and_another_rep_cannot_see_the_import(
    db_session: Session, app: FastAPI, rep_client: TestClient, finished_import: uuid.UUID
) -> None:
    """Assigning needs a manager (403 for a rep); a different rep gets 404 for the report."""
    other = _client(db_session, app, make_user(db_session))

    assert rep_client.get(f"/imports/{finished_import}/unmatched-owners").status_code == 403
    assert other.get(f"/imports/{finished_import}/report").status_code == 404


def test_uploading_the_same_file_again_needs_import_anyway(
    rep_client: TestClient, finished_import: uuid.UUID
) -> None:
    """Same bytes: 409 duplicate_file names the earlier import; allow_duplicate=true is 201."""
    refused = _upload(rep_client, ROWS)
    accepted = _upload(rep_client, ROWS, allow_duplicate="true")

    assert refused.status_code == 409
    assert refused.json()["code"] == "duplicate_file"
    assert refused.json()["earlier_import_id"] == str(finished_import)
    assert accepted.status_code == 201


def test_rerunning_a_completed_import_changes_nothing(
    db_session: Session,
    rep_client: TestClient,
    storage: LocalDiskStorage,
    finished_import: uuid.UUID,
) -> None:
    """A repeated job (for example a retried task) is a no-op: counts and leads are unchanged."""
    before = rep_client.get(f"/imports/{finished_import}/report").json()
    people_before = len(db_session.scalars(select(Person.id)).all())

    _run_import_job(db_session, storage, finished_import)

    after = rep_client.get(f"/imports/{finished_import}/report").json()
    assert after == before
    assert after["status"] == ImportStatus.COMPLETED.value
    assert len(db_session.scalars(select(Person.id)).all()) == people_before
