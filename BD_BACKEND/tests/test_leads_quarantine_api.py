"""Tests for the /quarantine endpoints on a real PostgreSQL, driven through the real app (M2-B2).

Needed because the route layer enforces who may do what (any BD user lists, fixes and
releases; only the importer, a manager or an admin discards, D-107), keeps the fixed error
bodies (no lead data echoed back), and exposes release as "released: false" when a row is
still invalid. Users are synthetic and sign in through a real session cookie.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from csrf_client import CsrfTestClient
from factories.core import make_user
from factories.imports import make_import_file, make_raw_row
from factories.leads import make_quarantine_record
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import services
from app.core.models import User, UserRole
from app.db import get_session
from app.leads.contracts import ImportContext, RowOutcome, RowOutcomeKind, SourceRow
from app.leads.models import PersonEmail, QuarantineRecord, QuarantineStatus
from app.leads.quarantine import IngestUnavailableError
from app.leads.quarantine_api import get_release_ingest_row
from app.main import app as real_app

BASE_URL = "/quarantine"
VALID_PAYLOAD = {"first_name": "Jane", "email": "jane@acme.com"}
PERSONAL_PAYLOAD = {"first_name": "Jane", "email": "jane@gmail.com"}


@pytest.fixture
def app(db_session: Session) -> Iterator[FastAPI]:
    """The real app wired to the test's rolled-back session."""

    def session_override() -> Iterator[Session]:
        yield db_session

    real_app.dependency_overrides[get_session] = session_override
    yield real_app
    real_app.dependency_overrides.clear()


def _client(session: Session, app: FastAPI, user: User | None) -> TestClient:
    """A client signed in as the user through a real session cookie (or anonymous)."""
    client = CsrfTestClient(app)
    if user is not None:
        token, _ = services.create_session(session, user)
        client.cookies.set(get_settings().session_cookie_name, token)
    return client


def _parked(
    session: Session, importer: User, payload: dict[str, object] | None = None
) -> QuarantineRecord:
    """An open record on a raw row of a file uploaded by `importer`."""
    import_file = make_import_file(session, uploaded_by=importer.id)
    raw_row = make_raw_row(session, import_file=import_file)
    return make_quarantine_record(
        session,
        raw_row_id=raw_row.id,
        payload=payload if payload is not None else dict(PERSONAL_PAYLOAD),
        issues=["personal_email_only"],
    )


def _imports_everything(app: FastAPI) -> None:
    """Replace ingest_row with a fake that always imports (the real one arrives in M2-B4)."""

    def fake_ingest(session: Session, row: SourceRow, ctx: ImportContext) -> RowOutcome:
        return RowOutcome(kind=RowOutcomeKind.IMPORTED)

    app.dependency_overrides[get_release_ingest_row] = lambda: fake_ingest


# --- access ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", ""),
        ("get", f"/{uuid.uuid4()}"),
        ("patch", f"/{uuid.uuid4()}"),
        ("post", f"/{uuid.uuid4()}/release"),
        ("post", f"/{uuid.uuid4()}/discard"),
    ],
)
def test_every_quarantine_route_requires_a_session(
    db_session: Session, app: FastAPI, method: str, path: str
) -> None:
    """Without a session cookie no quarantine route works: 401, or 403 from the CSRF check."""
    client = _client(db_session, app, None)

    response = client.request(method.upper(), BASE_URL + path, json={"values": {"a": "b"}})

    # State-changing requests without a session fail the CSRF check (403) before the login
    # check (401) runs; reads reach the login check. Either way nothing is allowed.
    expected = {401} if method == "get" else {401, 403}
    assert response.status_code in expected


@pytest.mark.parametrize("role", list(UserRole))
def test_every_role_can_list_fix_and_release(
    db_session: Session, app: FastAPI, role: UserRole
) -> None:
    """Any BD user, whatever the role, may list, fix and release (D-107)."""
    importer = make_user(db_session)
    actor = make_user(db_session, role=role)
    record = _parked(db_session, importer)
    _imports_everything(app)
    client = _client(db_session, app, actor)

    fix = client.patch(f"{BASE_URL}/{record.id}", json={"values": {"email": "j@acme.com"}})

    assert client.get(BASE_URL).status_code == 200
    assert fix.status_code == 200
    assert client.post(f"{BASE_URL}/{record.id}/release").status_code == 200


# --- list and get ------------------------------------------------------------------------------


def test_list_shows_open_records_with_their_source(db_session: Session, app: FastAPI) -> None:
    """The default list holds open records with reasons, payload, file name and row number."""
    rep = make_user(db_session)
    record = _parked(db_session, rep)
    client = _client(db_session, app, rep)

    body = client.get(BASE_URL).json()

    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == str(record.id)
    assert item["status"] == "open"
    assert item["issues"] == ["personal_email_only"]
    assert item["payload"] == PERSONAL_PAYLOAD
    assert item["filename"].endswith(".csv")
    assert item["row_number"] is not None


def test_list_filters_by_status_and_issue_and_rejects_unknown_values(
    db_session: Session, app: FastAPI
) -> None:
    """status=all includes discarded rows, issue narrows by reason, and bad values give 422."""
    rep = make_user(db_session)
    kept = _parked(db_session, rep)
    gone = _parked(db_session, rep)
    gone.status = QuarantineStatus.DISCARDED
    # The database requires resolved_at exactly when the status is not open.
    gone.resolved_at = datetime(2026, 11, 26, tzinfo=UTC)
    db_session.flush()
    client = _client(db_session, app, rep)

    assert client.get(BASE_URL).json()["total"] == 1
    assert client.get(BASE_URL, params={"status": "all"}).json()["total"] == 2
    assert client.get(BASE_URL, params={"issue": "personal_email_only"}).json()["total"] == 1
    assert client.get(BASE_URL, params={"issue": "bad_email_format"}).json()["total"] == 0
    assert client.get(BASE_URL, params={"status": "nonsense"}).status_code == 422
    assert client.get(BASE_URL, params={"limit": 0}).status_code == 422
    assert kept.id != gone.id


def test_get_one_and_unknown_id(db_session: Session, app: FastAPI) -> None:
    """GET returns the record, and an unknown id gives a fixed 404 body."""
    rep = make_user(db_session)
    record = _parked(db_session, rep)
    client = _client(db_session, app, rep)

    assert client.get(f"{BASE_URL}/{record.id}").json()["id"] == str(record.id)
    missing = client.get(f"{BASE_URL}/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Quarantine record not found"}


# --- fix ---------------------------------------------------------------------------------------


def test_patch_adds_a_work_email_and_refreshes_the_reasons(
    db_session: Session, app: FastAPI
) -> None:
    """PATCH merges the new value into the payload and returns the refreshed reasons."""
    rep = make_user(db_session)
    record = _parked(db_session, rep)
    client = _client(db_session, app, rep)

    response = client.patch(f"{BASE_URL}/{record.id}", json={"values": {"email": "jane@acme.com"}})

    assert response.status_code == 200
    assert response.json()["issues"] == []
    assert response.json()["payload"]["email"] == "jane@acme.com"


def test_patch_rejects_bad_input(db_session: Session, app: FastAPI) -> None:
    """A bad field name gives 422 without echoing it; an empty or unknown body gives 422."""
    rep = make_user(db_session)
    record = _parked(db_session, rep)
    client = _client(db_session, app, rep)

    bad_name = client.patch(f"{BASE_URL}/{record.id}", json={"values": {"Bad Name": "x"}})
    empty = client.patch(f"{BASE_URL}/{record.id}", json={"values": {}})
    extra = client.patch(f"{BASE_URL}/{record.id}", json={"values": {"a": "b"}, "other": 1})

    assert bad_name.status_code == 422
    assert empty.status_code == 422
    assert extra.status_code == 422


def test_patch_of_a_discarded_record_conflicts(db_session: Session, app: FastAPI) -> None:
    """Editing a record that was already discarded answers 409."""
    rep = make_user(db_session)
    record = _parked(db_session, rep)
    client = _client(db_session, app, rep)
    client.post(f"{BASE_URL}/{record.id}/discard")

    response = client.patch(f"{BASE_URL}/{record.id}", json={"values": {"email": "a@b.com"}})

    assert response.status_code == 409


# --- release -----------------------------------------------------------------------------------


def test_release_of_an_invalid_row_reports_released_false(
    db_session: Session, app: FastAPI
) -> None:
    """A row that still fails validation stays open and the response says released: false."""
    rep = make_user(db_session)
    record = _parked(db_session, rep)
    client = _client(db_session, app, rep)

    body = client.post(f"{BASE_URL}/{record.id}/release").json()

    assert body["released"] is False
    assert body["outcome"] is None
    assert body["record"]["status"] == "open"
    assert body["record"]["issues"] == ["personal_email_only"]


def test_release_of_a_valid_row_with_a_fake_ingest_resolves_it(
    db_session: Session, app: FastAPI
) -> None:
    """With ingest_row available, a valid row is released and the record resolves."""
    rep = make_user(db_session)
    record = _parked(db_session, rep, payload=dict(VALID_PAYLOAD))
    _imports_everything(app)
    client = _client(db_session, app, rep)

    body = client.post(f"{BASE_URL}/{record.id}/release").json()

    assert body["released"] is True
    assert body["outcome"] == "imported"
    assert body["record"]["status"] == "released"
    assert body["record"]["resolved_by"] == str(rep.id)


def test_release_of_a_valid_row_uses_the_real_ingest_row(db_session: Session, app: FastAPI) -> None:
    """With no override the real ingest_row runs: the record resolves and a person exists."""
    rep = make_user(db_session)
    record = _parked(db_session, rep, payload=dict(VALID_PAYLOAD))
    client = _client(db_session, app, rep)

    body = client.post(f"{BASE_URL}/{record.id}/release").json()

    assert body["released"] is True
    assert body["outcome"] == "imported"
    assert db_session.scalars(
        select(PersonEmail).where(PersonEmail.normalized_address == "jane@acme.com")
    ).one()


def test_release_answers_503_when_ingest_row_refuses(db_session: Session, app: FastAPI) -> None:
    """A stand-in that raises IngestUnavailableError gives 503 and the record stays open."""
    rep = make_user(db_session)
    record = _parked(db_session, rep, payload=dict(VALID_PAYLOAD))

    def unavailable(session: Session, row: SourceRow, ctx: ImportContext) -> RowOutcome:
        """Refuse like a missing ingest_row."""
        raise IngestUnavailableError

    app.dependency_overrides[get_release_ingest_row] = lambda: unavailable
    client = _client(db_session, app, rep)

    response = client.post(f"{BASE_URL}/{record.id}/release")

    assert response.status_code == 503
    assert response.json() == {"detail": "Releasing valid rows is not available yet."}
    db_session.refresh(record)
    assert record.status == QuarantineStatus.OPEN


def test_release_twice_conflicts(db_session: Session, app: FastAPI) -> None:
    """Releasing an already released record answers 409."""
    rep = make_user(db_session)
    record = _parked(db_session, rep, payload=dict(VALID_PAYLOAD))
    _imports_everything(app)
    client = _client(db_session, app, rep)
    client.post(f"{BASE_URL}/{record.id}/release")

    assert client.post(f"{BASE_URL}/{record.id}/release").status_code == 409


# --- discard -----------------------------------------------------------------------------------


def test_discard_by_importer_manager_and_admin_but_not_another_rep(
    db_session: Session, app: FastAPI
) -> None:
    """Importer, manager and admin may discard; another rep gets 403 with the fixed body."""
    importer = make_user(db_session)
    other_rep = make_user(db_session)
    manager = make_user(db_session, role=UserRole.MANAGER)
    admin = make_user(db_session, role=UserRole.ADMIN)
    records = [_parked(db_session, importer) for _ in range(4)]

    denied = _client(db_session, app, other_rep).post(f"{BASE_URL}/{records[0].id}/discard")
    by_importer = _client(db_session, app, importer).post(f"{BASE_URL}/{records[0].id}/discard")
    by_manager = _client(db_session, app, manager).post(f"{BASE_URL}/{records[1].id}/discard")
    by_admin = _client(db_session, app, admin).post(f"{BASE_URL}/{records[2].id}/discard")

    assert denied.status_code == 403
    assert denied.json() == {"detail": "Not permitted"}
    assert by_importer.status_code == 200
    assert by_manager.json()["status"] == "discarded"
    assert by_admin.status_code == 200
    db_session.refresh(records[3])
    assert records[3].status == QuarantineStatus.OPEN


def test_discard_unknown_and_twice(db_session: Session, app: FastAPI) -> None:
    """An unknown id gives 404 and a second discard of the same record gives 409."""
    rep = make_user(db_session)
    record = _parked(db_session, rep)
    client = _client(db_session, app, rep)

    assert client.post(f"{BASE_URL}/{uuid.uuid4()}/discard").status_code == 404
    assert client.post(f"{BASE_URL}/{record.id}/discard").status_code == 200
    assert client.post(f"{BASE_URL}/{record.id}/discard").status_code == 409
