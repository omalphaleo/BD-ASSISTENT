"""Tests for the /imports upload, status and worksheet endpoints on a real PostgreSQL database.

Needed because M2-A1's rules meet here: the duplicate-file warning and "import anyway" (D-109),
the 20 MB limit enforced while the body streams in (D-110), nothing stored for a refused
file, per-role visibility, the worksheet choice for multi-sheet workbooks, and the audit
events. They drive the real app with synthetic users and a temporary upload directory.
"""

import io
import uuid
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from csrf_client import CsrfTestClient
from fastapi import FastAPI
from fastapi.testclient import TestClient
from import_files import multipart_body, sample_csv, sheet_rows, xlsx_bytes
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.audit.services import AuditAction
from app.config import get_settings
from app.core import services
from app.core.models import User, UserRole
from app.db import get_session
from app.imports import api as imports_api
from app.imports.models import ImportFile, ImportStatus
from app.imports.parsers import UploadLimits, limits_from_settings
from app.imports.storage import LocalDiskStorage, get_file_storage
from app.imports.upload import DuplicateFileError, clean_display_name, receive_upload
from app.main import app as real_app

UPLOAD_URL = "/imports/upload"


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    """A throwaway upload directory, so tests never touch a real volume."""
    return tmp_path / "uploads"


@pytest.fixture
def app(db_session: Session, storage_dir: Path) -> Iterator[FastAPI]:
    """The real app wired to the test's rolled-back session and the temporary directory."""

    def session_override() -> Iterator[Session]:
        yield db_session

    real_app.dependency_overrides[get_session] = session_override
    real_app.dependency_overrides[get_file_storage] = lambda: LocalDiskStorage(storage_dir)
    yield real_app
    real_app.dependency_overrides.clear()


def _make_user(session: Session, role: UserRole, *, name: str | None = None) -> User:
    """Insert a synthetic active user (a placeholder hash is enough: no login happens)."""
    user = User(
        email=f"{name or role.value}@example.com", password_hash="not-a-real-hash", role=role
    )
    session.add(user)
    session.flush()
    return user


def _client(session: Session, app: FastAPI, user: User | None) -> TestClient:
    """A client signed in as the user through a real session cookie (or anonymous)."""
    client = CsrfTestClient(app)
    if user is not None:
        token, _ = services.create_session(session, user)
        client.cookies.set(get_settings().session_cookie_name, token)
    return client


def _upload(client: TestClient, content: bytes, filename: str = "leads.csv", **fields: str):
    """POST a file as multipart form data, as the browser would."""
    return client.post(
        UPLOAD_URL,
        files={"file": (filename, content, "application/octet-stream")},
        data=fields or None,
    )


def _stored_files(storage_dir: Path) -> list[str]:
    """Names of the objects currently in the upload directory."""
    return sorted(p.name for p in storage_dir.iterdir()) if storage_dir.exists() else []


def _actions(session: Session) -> list[str]:
    """Audit actions recorded so far, oldest first."""
    rows = session.execute(select(AuditLog).order_by(AuditLog.occurred_at)).scalars()
    return [row.action for row in rows]


def _import_count(session: Session) -> int:
    """Number of ImportFile rows."""
    return session.scalar(select(func.count()).select_from(ImportFile)) or 0


@pytest.fixture
def rep(db_session: Session) -> User:
    """A synthetic rep."""
    return _make_user(db_session, UserRole.REP)


# --- access ----------------------------------------------------------------------------------


def test_anonymous_gets_401_on_every_import_endpoint(app: FastAPI, db_session: Session) -> None:
    """Nobody signed in: status is 401; the two POSTs are refused (403) by the CSRF check first."""
    client = _client(db_session, app, None)
    some_id = uuid.uuid4()
    assert client.get(f"/imports/{some_id}").status_code == 401
    # No session means no CSRF token, and the app-level CSRF guard answers before the
    # permission guard does; either way nothing is stored.
    assert _upload(client, sample_csv()).status_code == 403
    assert client.post(f"/imports/{some_id}/worksheet", json={"worksheet": "A"}).status_code == 403


@pytest.mark.parametrize("role", list(UserRole), ids=lambda r: r.value)
def test_every_role_may_upload(app: FastAPI, db_session: Session, role: UserRole) -> None:
    """IMPORT_LEADS is granted to rep, manager and admin, so each gets 201."""
    client = _client(db_session, app, _make_user(db_session, role))
    assert _upload(client, sample_csv()).status_code == 201


# --- a successful upload ---------------------------------------------------------------------


def test_csv_upload_stores_the_file_and_registers_it(
    app: FastAPI, db_session: Session, rep: User, storage_dir: Path
) -> None:
    """201 with row count and headers; bytes stored; row in the database; one audit event."""
    content = sample_csv(data_rows=3)

    response = _upload(_client(db_session, app, rep), content, "My Leads.csv")

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "My Leads.csv"
    assert body["status"] == "uploaded"
    assert body["row_count"] == 3
    assert body["size_bytes"] == len(content)
    assert body["uploaded_by"] == str(rep.id)
    assert body["headers"] == ["First Name", "Last Name", "Email"]
    assert body["worksheets"] == [] and body["worksheet"] is None
    assert "storage_key" not in body  # the key and server paths are never returned

    row = db_session.get(ImportFile, uuid.UUID(body["id"]))
    assert row is not None and row.status is ImportStatus.UPLOADED
    assert row.storage_key is not None and _stored_files(storage_dir) == [row.storage_key]
    assert (storage_dir / row.storage_key).read_bytes() == content
    assert _actions(db_session) == [AuditAction.IMPORT_FILE_UPLOADED.value]


def test_audit_summary_holds_no_file_name_or_content(
    app: FastAPI, db_session: Session, rep: User
) -> None:
    """The audit event records format, size and counts only, never the name or the rows."""
    _upload(_client(db_session, app, rep), sample_csv(), "secret-name.csv")
    event = db_session.execute(select(AuditLog)).scalars().one()
    assert event.summary == {
        "step": "uploaded",
        "file_format": "csv",
        "size_bytes": len(sample_csv()),
        "row_count": 3,
        "worksheet_count": 0,
    }
    assert "secret-name" not in str(event.summary)


def test_single_sheet_xlsx_is_selected_automatically(
    app: FastAPI, db_session: Session, rep: User
) -> None:
    """A one-sheet workbook comes back with its worksheet already chosen and its headers."""
    response = _upload(
        _client(db_session, app, rep), xlsx_bytes({"Leads": sheet_rows(2)}), "leads.xlsx"
    )
    body = response.json()
    assert response.status_code == 201
    assert body["worksheet"] == "Leads" and body["row_count"] == 2
    assert body["headers"] == ["First Name", "Last Name", "Email"]


def test_display_name_never_keeps_directories_or_control_characters() -> None:
    """The client's file name is only a label: path parts and control characters are removed."""
    assert clean_display_name("../../etc/passwd.csv") == "passwd.csv"
    assert clean_display_name("C:\\Users\\x\\leads.csv") == "leads.csv"
    assert clean_display_name("a\x00b\nc.csv") == "abc.csv"
    assert clean_display_name("") == "upload"
    assert len(clean_display_name("x" * 400 + ".csv")) == 255


# --- duplicate files (D-109) -----------------------------------------------------------------


def test_same_file_twice_warns_with_earlier_date_and_user_and_stores_nothing(
    app: FastAPI, db_session: Session, rep: User, storage_dir: Path
) -> None:
    """The second identical upload is 409 with who and when; no new row and no new file."""
    first = _upload(_client(db_session, app, rep), sample_csv())
    other = _make_user(db_session, UserRole.MANAGER)

    second = _upload(_client(db_session, app, other), sample_csv(), "renamed.csv")

    assert second.status_code == 409
    body = second.json()
    assert body["code"] == "duplicate_file"
    assert body["earlier_import_id"] == first.json()["id"]
    assert body["earlier_uploaded_by"] == "rep@example.com"
    assert body["earlier_uploaded_at"]
    assert _import_count(db_session) == 1
    assert len(_stored_files(storage_dir)) == 1


def test_import_anyway_uploads_again_and_audits_the_override(
    app: FastAPI, db_session: Session, rep: User, storage_dir: Path
) -> None:
    """Re-uploading with allow_duplicate=true is 201; hashes stay non-unique; override audited."""
    client = _client(db_session, app, rep)
    first = _upload(client, sample_csv())

    again = _upload(client, sample_csv(), allow_duplicate="true")

    assert again.status_code == 201
    assert again.json()["id"] != first.json()["id"]
    hashes = db_session.execute(select(ImportFile.sha256)).scalars().all()
    assert len(hashes) == 2 and hashes[0] == hashes[1]
    assert len(_stored_files(storage_dir)) == 2
    assert _actions(db_session) == [
        AuditAction.IMPORT_FILE_UPLOADED.value,
        AuditAction.IMPORT_FILE_UPLOADED.value,
        AuditAction.IMPORT_DUPLICATE_FILE_OVERRIDDEN.value,
    ]


def test_allow_duplicate_on_a_new_file_records_no_override(
    app: FastAPI, db_session: Session, rep: User
) -> None:
    """The flag alone does nothing: with no earlier identical file there is no override event."""
    _upload(_client(db_session, app, rep), sample_csv(), allow_duplicate="true")
    assert _actions(db_session) == [AuditAction.IMPORT_FILE_UPLOADED.value]


def test_different_content_is_not_a_duplicate(app: FastAPI, db_session: Session, rep: User) -> None:
    """Two files with different content both upload without a warning."""
    client = _client(db_session, app, rep)
    assert _upload(client, sample_csv(data_rows=2)).status_code == 201
    assert _upload(client, sample_csv(data_rows=3)).status_code == 201


# --- refusals: nothing is stored -------------------------------------------------------------


def test_unsupported_file_type_is_415_and_stores_nothing(
    app: FastAPI, db_session: Session, rep: User, storage_dir: Path
) -> None:
    """A .xls (or any other type) is refused with 415 and the unsupported_type code."""
    response = _upload(_client(db_session, app, rep), b"whatever", "old.xls")
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_type"
    assert _import_count(db_session) == 0 and _stored_files(storage_dir) == []


def test_ambiguous_csv_is_422_with_a_fixed_message(
    app: FastAPI, db_session: Session, rep: User, storage_dir: Path
) -> None:
    """A single-column CSV is refused; the message is fixed text, not the file's content."""
    response = _upload(_client(db_session, app, rep), b"Email\r\nsecret@example.com\r\n")
    assert response.status_code == 422
    assert response.json()["code"] == "ambiguous_csv"
    assert "secret@example.com" not in response.text
    assert _import_count(db_session) == 0 and _stored_files(storage_dir) == []


def test_too_many_rows_is_422(
    app: FastAPI, db_session: Session, rep: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file with more data rows than the limit is refused with too_many_rows."""
    small = replace(limits_from_settings(get_settings()), max_rows=3)
    monkeypatch.setattr(imports_api, "_limits", lambda: small)
    response = _upload(_client(db_session, app, rep), sample_csv(data_rows=4))
    assert response.status_code == 422
    assert response.json()["code"] == "too_many_rows"


def _small_byte_limit(monkeypatch: pytest.MonkeyPatch, max_bytes: int) -> UploadLimits:
    """Make the endpoints use a tiny byte limit for the test."""
    limits = replace(limits_from_settings(get_settings()), max_bytes=max_bytes)
    monkeypatch.setattr(imports_api, "_limits", lambda: limits)
    return limits


def test_oversized_upload_is_413_from_the_content_length(
    app: FastAPI,
    db_session: Session,
    rep: User,
    storage_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A body whose declared length is far over the limit is refused with 413 straight away."""
    limits = _small_byte_limit(monkeypatch, 1_000)
    body, content_type = multipart_body("big.csv", b"a,b\r\n" + b"1,2\r\n" * 40_000)
    assert len(body) > limits.max_bytes + 64 * 1024

    response = _client(db_session, app, rep).post(
        UPLOAD_URL, content=body, headers={"content-type": content_type}
    )

    assert response.status_code == 413
    assert response.json()["code"] == "too_large"
    assert _import_count(db_session) == 0 and _stored_files(storage_dir) == []


def test_oversized_chunked_upload_is_stopped_while_streaming(
    app: FastAPI,
    db_session: Session,
    rep: User,
    storage_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no Content-Length (chunked body) the limit is still enforced as bytes arrive."""
    _small_byte_limit(monkeypatch, 1_000)
    body, content_type = multipart_body("big.csv", b"a,b\r\n" + b"1,2\r\n" * 40_000)
    chunks = (body[i : i + 8192] for i in range(0, len(body), 8192))

    response = _client(db_session, app, rep).post(
        UPLOAD_URL, content=chunks, headers={"content-type": content_type}
    )

    assert response.status_code == 413
    assert response.json()["code"] == "too_large"
    assert _import_count(db_session) == 0 and _stored_files(storage_dir) == []


def test_file_just_over_the_limit_inside_the_form_allowance_is_413(
    app: FastAPI, db_session: Session, rep: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file larger than the limit but small enough to pass the body check is still refused."""
    _small_byte_limit(monkeypatch, 100)
    response = _upload(_client(db_session, app, rep), sample_csv(data_rows=20))
    assert response.status_code == 413


def test_a_body_without_a_file_part_is_422(app: FastAPI, db_session: Session, rep: User) -> None:
    """A form with no 'file' field, or a non-multipart body, is refused as malformed."""
    client = _client(db_session, app, rep)
    no_file = client.post(UPLOAD_URL, data={"allow_duplicate": "true"})
    not_multipart = client.post(UPLOAD_URL, json={"file": "x"})
    for response in (no_file, not_multipart):
        assert response.status_code == 422
        assert response.json()["code"] == "malformed_file"


# --- transaction safety ----------------------------------------------------------------------


def test_failed_commit_removes_the_stored_file(
    db_session: Session, rep: User, storage_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the database commit fails after the file was stored, the stored file is deleted."""
    content = sample_csv()

    def failing_commit() -> None:
        raise OperationalError("COMMIT", {}, Exception("simulated outage"))

    monkeypatch.setattr(db_session, "commit", failing_commit)
    with pytest.raises(OperationalError):
        receive_upload(
            db_session,
            rep,
            source=io.BytesIO(content),
            size_bytes=len(content),
            sha256="0" * 64,
            filename="x.csv",
            allow_duplicate=False,
            storage=LocalDiskStorage(storage_dir),
            limits=limits_from_settings(get_settings()),
        )
    assert _stored_files(storage_dir) == []


def test_duplicate_error_carries_the_earlier_upload(
    db_session: Session, rep: User, storage_dir: Path
) -> None:
    """The service raises DuplicateFileError (not a row) for identical content."""
    content = sample_csv()
    kwargs = {
        "source": io.BytesIO(content),
        "size_bytes": len(content),
        "sha256": "1" * 64,
        "filename": "x.csv",
        "allow_duplicate": False,
        "storage": LocalDiskStorage(storage_dir),
        "limits": limits_from_settings(get_settings()),
    }
    first = receive_upload(db_session, rep, **kwargs)
    kwargs["source"] = io.BytesIO(content)
    with pytest.raises(DuplicateFileError) as caught:
        receive_upload(db_session, rep, **kwargs)
    assert caught.value.duplicate.import_file_id == first.import_file.id


# --- status visibility -----------------------------------------------------------------------


def test_visibility_by_role(app: FastAPI, db_session: Session, rep: User) -> None:
    """Uploader, manager and admin see it; another rep gets the same 404 as for a missing one."""
    import_id = _upload(_client(db_session, app, rep), sample_csv()).json()["id"]
    other_rep = _make_user(db_session, UserRole.REP, name="other-rep")
    manager = _make_user(db_session, UserRole.MANAGER)
    admin = _make_user(db_session, UserRole.ADMIN)

    for viewer in (rep, manager, admin):
        response = _client(db_session, app, viewer).get(f"/imports/{import_id}")
        assert response.status_code == 200 and response.json()["id"] == import_id
        assert "storage_key" not in response.json()

    hidden = _client(db_session, app, other_rep).get(f"/imports/{import_id}")
    missing = _client(db_session, app, other_rep).get(f"/imports/{uuid.uuid4()}")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


# --- worksheet selection ---------------------------------------------------------------------


def _multi_sheet(app: FastAPI, db_session: Session, rep: User) -> str:
    """Upload a three-sheet workbook and return its import id."""
    book = xlsx_bytes(
        {"Alpha": sheet_rows(2), "Beta": sheet_rows(5), "Empty": [["H1", "H2", "H3"]]}
    )
    response = _upload(_client(db_session, app, rep), book, "book.xlsx")
    assert response.status_code == 201
    body = response.json()
    assert body["worksheet"] is None and body["row_count"] == 0
    assert [(w["name"], w["row_count"], w["selectable"]) for w in body["worksheets"]] == [
        ("Alpha", 2, True),
        ("Beta", 5, True),
        ("Empty", 0, False),
    ]
    return body["id"]


def test_uploader_chooses_a_worksheet(app: FastAPI, db_session: Session, rep: User) -> None:
    """Choosing a sheet sets the worksheet and row count and is audited."""
    import_id = _multi_sheet(app, db_session, rep)

    response = _client(db_session, app, rep).post(
        f"/imports/{import_id}/worksheet", json={"worksheet": "Beta"}
    )

    assert response.status_code == 200
    assert response.json()["worksheet"] == "Beta" and response.json()["row_count"] == 5
    last = (
        db_session.execute(select(AuditLog).order_by(AuditLog.occurred_at.desc())).scalars().first()
    )
    assert last is not None and last.action == AuditAction.IMPORT_FILE_UPLOADED.value
    assert last.summary == {"step": "worksheet_selected", "worksheet": "Beta", "row_count": 5}


@pytest.mark.parametrize(("sheet", "code"), [("Nope", "bad_worksheet"), ("Empty", "bad_worksheet")])
def test_unknown_or_empty_worksheet_is_422(
    app: FastAPI, db_session: Session, rep: User, sheet: str, code: str
) -> None:
    """A sheet that does not exist or has no data rows cannot be chosen."""
    import_id = _multi_sheet(app, db_session, rep)
    response = _client(db_session, app, rep).post(
        f"/imports/{import_id}/worksheet", json={"worksheet": sheet}
    )
    assert response.status_code == 422 and response.json()["code"] == code


def test_oversized_worksheet_cannot_be_chosen(
    app: FastAPI, db_session: Session, rep: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sheet over the row limit is listed at upload but refused when chosen."""
    import_id = _multi_sheet(app, db_session, rep)
    small = replace(limits_from_settings(get_settings()), max_rows=3)
    monkeypatch.setattr(imports_api, "_limits", lambda: small)
    response = _client(db_session, app, rep).post(
        f"/imports/{import_id}/worksheet", json={"worksheet": "Beta"}
    )
    assert response.status_code == 422 and response.json()["code"] == "bad_worksheet"


def test_only_the_uploader_may_choose_and_others_cannot_see_it(
    app: FastAPI, db_session: Session, rep: User
) -> None:
    """A manager can view but not change the import (409); another rep gets 404."""
    import_id = _multi_sheet(app, db_session, rep)
    manager = _make_user(db_session, UserRole.MANAGER)
    other_rep = _make_user(db_session, UserRole.REP, name="other-rep")

    by_manager = _client(db_session, app, manager).post(
        f"/imports/{import_id}/worksheet", json={"worksheet": "Alpha"}
    )
    by_other = _client(db_session, app, other_rep).post(
        f"/imports/{import_id}/worksheet", json={"worksheet": "Alpha"}
    )

    assert by_manager.status_code == 409 and by_manager.json()["code"] == "not_editable"
    assert by_other.status_code == 404


def test_csv_import_has_no_worksheet_to_choose(
    app: FastAPI, db_session: Session, rep: User
) -> None:
    """Choosing a worksheet on a CSV import is refused."""
    client = _client(db_session, app, rep)
    import_id = _upload(client, sample_csv()).json()["id"]
    response = client.post(f"/imports/{import_id}/worksheet", json={"worksheet": "Sheet1"})
    assert response.status_code == 422 and response.json()["code"] == "bad_worksheet"


def test_worksheet_cannot_change_after_processing_started(
    app: FastAPI, db_session: Session, rep: User
) -> None:
    """Once the import is processing, the worksheet is locked (409)."""
    import_id = _multi_sheet(app, db_session, rep)
    row = db_session.get(ImportFile, uuid.UUID(import_id))
    assert row is not None
    row.status = ImportStatus.PROCESSING
    db_session.flush()
    response = _client(db_session, app, rep).post(
        f"/imports/{import_id}/worksheet", json={"worksheet": "Alpha"}
    )
    assert response.status_code == 409 and response.json()["code"] == "not_editable"


def test_worksheet_body_is_validated(app: FastAPI, db_session: Session, rep: User) -> None:
    """A missing or empty worksheet name is a 422 validation error."""
    client = _client(db_session, app, rep)
    import_id = _multi_sheet(app, db_session, rep)
    assert client.post(f"/imports/{import_id}/worksheet", json={}).status_code == 422
    assert client.post(f"/imports/{import_id}/worksheet", json={"worksheet": ""}).status_code == 422
