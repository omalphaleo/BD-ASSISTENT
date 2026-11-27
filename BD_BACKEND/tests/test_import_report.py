"""Tests for the import report, change summary and CSV downloads (M2-A5) on real PostgreSQL.

Needed because the report is how a user trusts an import (D-050): totals and reasons must be
read back correctly, the change list must page, the failed-rows file must keep the uploaded
columns and hide nothing dangerous, and every download must be limited to the importer, managers
and admins and audited (D-111). The rows an import wrote are built with factories, because W2's
ingest_row and merge code do not exist yet. All data is synthetic.
"""

import csv
import io
import uuid
from collections.abc import Iterator

import pytest
from csrf_client import CsrfTestClient
from factories.core import make_user
from factories.imports import (
    make_column_mapping,
    make_import_change,
    make_import_file,
    make_import_report,
    make_raw_row,
)
from factories.leads import make_person, make_person_email
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.audit.services import AuditAction
from app.config import get_settings
from app.core import services
from app.core.models import User, UserRole
from app.db import get_session
from app.imports.downloads import neutralise_cell
from app.imports.models import ImportFile, ImportReport, ImportStatus
from app.imports.reports import CHANGES_PAGE_SIZE
from app.leads.contracts import RowOutcomeKind
from app.main import app as real_app

HEADERS = ["First Name", "Email", "Company"]


@pytest.fixture
def app(db_session: Session) -> Iterator[FastAPI]:
    """The real app wired to the test session."""

    def session_override() -> Iterator[Session]:
        yield db_session

    real_app.dependency_overrides[get_session] = session_override
    yield real_app
    real_app.dependency_overrides.clear()


def _client(session: Session, app: FastAPI, user: User) -> TestClient:
    """A client signed in as the user through a real session cookie."""
    client = CsrfTestClient(app)
    token, _ = services.create_session(session, user)
    client.cookies.set(get_settings().session_cookie_name, token)
    return client


def _finished_import(
    db: Session, uploader: User, *, status: ImportStatus = ImportStatus.COMPLETED
) -> tuple[ImportFile, ImportReport]:
    """An import with a saved mapping for HEADERS and a report, owned by the uploader."""
    import_file = make_import_file(db, status=status, uploaded_by=uploader.id, row_count=4)
    for index, header in enumerate(HEADERS):
        make_column_mapping(
            db, import_file=import_file, column_index=index, source_header=header, target_field=None
        )
    report = make_import_report(
        db,
        import_file=import_file,
        received=4,
        imported=1,
        updated=1,
        rejected=1,
        quarantined=1,
        failure_reasons={"personal_email_only": 1, "ingest_error": 1},
    )
    return import_file, report


def _failed_row(
    db: Session,
    import_file: ImportFile,
    row_number: int,
    outcome: RowOutcomeKind,
    reason: str | None,
    values: dict[str, object],
) -> None:
    """Store one raw row with its processing result, as the pipeline does."""
    make_raw_row(
        db,
        import_file=import_file,
        row_number=row_number,
        original_values=values,
        email_normalized=None,
        outcome=outcome,
        reason_code=reason,
    )


def _csv_rows(text: str) -> list[list[str]]:
    """Parse CSV text into rows."""
    return list(csv.reader(io.StringIO(text)))


def _download_audits(db: Session) -> list[AuditLog]:
    """The report-download audit events written so far."""
    return list(
        db.scalars(
            select(AuditLog).where(AuditLog.action == AuditAction.IMPORT_REPORT_DOWNLOADED.value)
        )
    )


# --- neutralise_cell ---------------------------------------------------------------------------


@pytest.mark.parametrize("risky", ["=1+1", "+1", "-1", "@SUM(A1)", "\tcmd", "\rcmd"])
def test_formula_characters_get_a_leading_apostrophe(risky: str) -> None:
    """A cell starting with = + - @ tab or CR is written as text, never as a formula."""
    assert neutralise_cell(risky) == "'" + risky


def test_plain_cells_are_left_alone() -> None:
    """Ordinary text, empty cells and None are written unchanged (None as empty)."""
    assert neutralise_cell("Ada") == "Ada"
    assert neutralise_cell("a=b") == "a=b"
    assert neutralise_cell(None) == ""
    assert neutralise_cell(7) == "7"


# --- report ------------------------------------------------------------------------------------


def test_report_shows_totals_and_reasons_most_frequent_first(
    db_session: Session, app: FastAPI
) -> None:
    """The report returns the seven totals and the failure reasons sorted by count, then code."""
    rep = make_user(db_session)
    import_file, report = _finished_import(db_session, rep)
    report.failure_reasons = {"b_reason": 1, "a_reason": 1, "common": 5}
    db_session.commit()

    response = _client(db_session, app, rep).get(f"/imports/{import_file.id}/report")

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["received"], body["imported"], body["updated"], body["rejected"]) == (4, 1, 1, 1)
    assert body["status"] == "completed"
    assert [r["code"] for r in body["failure_reasons"]] == ["common", "a_reason", "b_reason"]
    assert body["changes_total"] == 0


def test_report_of_a_failed_import_is_still_readable(db_session: Session, app: FastAPI) -> None:
    """A FAILED import keeps its committed chunks, so its partial report can be read."""
    rep = make_user(db_session)
    import_file, _ = _finished_import(db_session, rep, status=ImportStatus.FAILED)

    response = _client(db_session, app, rep).get(f"/imports/{import_file.id}/report")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"


@pytest.mark.parametrize("status", [ImportStatus.UPLOADED, ImportStatus.PROCESSING])
def test_report_changes_and_downloads_are_refused_until_the_import_finishes(
    db_session: Session, app: FastAPI, status: ImportStatus
) -> None:
    """Before COMPLETED or FAILED every report route answers 409 and no download is audited."""
    rep = make_user(db_session)
    import_file, _ = _finished_import(db_session, rep, status=status)
    client = _client(db_session, app, rep)

    for path in ("report", "changes", "download/failed-rows.csv", "download/changes.csv"):
        response = client.get(f"/imports/{import_file.id}/{path}")
        assert response.status_code == 409, path
        assert response.json()["code"] == "not_finished"
    assert _download_audits(db_session) == []


def test_import_without_a_report_row_is_not_finished(db_session: Session, app: FastAPI) -> None:
    """A finished status but no report row (it never ran) answers 409, not a server error."""
    rep = make_user(db_session)
    import_file = make_import_file(db_session, status=ImportStatus.FAILED, uploaded_by=rep.id)

    response = _client(db_session, app, rep).get(f"/imports/{import_file.id}/report")

    assert response.status_code == 409


# --- who may read ------------------------------------------------------------------------------


def test_other_rep_gets_404_but_managers_and_admins_can_read_and_download(
    db_session: Session, app: FastAPI
) -> None:
    """D-111: the importer, managers and admins see the report and files; another rep gets 404."""
    owner = make_user(db_session)
    import_file, _ = _finished_import(db_session, owner)
    other = make_user(db_session)
    manager = make_user(db_session, role=UserRole.MANAGER)
    admin = make_user(db_session, role=UserRole.ADMIN)
    paths = ("report", "changes", "download/failed-rows.csv", "download/changes.csv")

    for allowed in (owner, manager, admin):
        client = _client(db_session, app, allowed)
        assert all(client.get(f"/imports/{import_file.id}/{p}").status_code == 200 for p in paths)
    denied = _client(db_session, app, other)
    assert all(denied.get(f"/imports/{import_file.id}/{p}").status_code == 404 for p in paths)
    assert denied.get(f"/imports/{uuid.uuid4()}/report").status_code == 404


def test_anonymous_requests_are_refused(db_session: Session, app: FastAPI) -> None:
    """Without a session cookie the report routes answer 401."""
    import_file, _ = _finished_import(db_session, make_user(db_session))

    response = TestClient(app).get(f"/imports/{import_file.id}/report")

    assert response.status_code == 401


# --- change summary ----------------------------------------------------------------------------


def test_changes_list_shows_labels_old_and_new_values_and_the_primary_email(
    db_session: Session, app: FastAPI
) -> None:
    """Each changed lead shows its name, primary email and labelled old and new values."""
    rep = make_user(db_session)
    import_file, report = _finished_import(db_session, rep)
    person = make_person(db_session, first_name="Ada", last_name="Lovelace")
    make_person_email(db_session, person=person, address="second@acme.example")
    make_person_email(db_session, person=person, address="main@acme.example", is_primary=True)
    make_import_change(
        db_session,
        report=report,
        person=person,
        changes=[
            {"field": "title", "old": "Engineer", "new": "CTO"},
            {"field": "no_such_field", "old": None, "new": 5},
            {"broken": True},  # an item of the wrong shape is skipped
        ],
    )

    response = _client(db_session, app, rep).get(f"/imports/{import_file.id}/changes")

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["total"], body["page"], body["page_size"]) == (1, 1, CHANGES_PAGE_SIZE)
    (item,) = body["items"]
    assert (item["name"], item["email"]) == ("Ada Lovelace", "main@acme.example")
    assert item["changes"][0] == {
        "field": "title",
        "label": item["changes"][0]["label"],
        "old": "Engineer",
        "new": "CTO",
    }
    assert item["changes"][0]["label"] != "title"  # the human label, not the key
    assert item["changes"][1]["label"] == "no_such_field"  # unknown keys fall back to the key
    assert len(item["changes"]) == 2


def test_changes_are_paged_in_a_stable_order(db_session: Session, app: FastAPI) -> None:
    """51 changed leads make two pages (50 and 1) with the same total and no repeats."""
    rep = make_user(db_session)
    import_file, report = _finished_import(db_session, rep)
    for n in range(CHANGES_PAGE_SIZE + 1):
        make_import_change(
            db_session, report=report, person=make_person(db_session, last_name=f"L{n:03d}")
        )
    client = _client(db_session, app, rep)

    first = client.get(f"/imports/{import_file.id}/changes?page=1").json()
    second = client.get(f"/imports/{import_file.id}/changes?page=2").json()

    assert (first["total"], second["total"]) == (51, 51)
    assert (len(first["items"]), len(second["items"])) == (50, 1)
    ids = [i["person_id"] for i in first["items"] + second["items"]]
    assert len(set(ids)) == 51
    assert client.get(f"/imports/{import_file.id}/changes?page=0").status_code == 422


def test_changes_csv_has_one_line_per_field_and_is_audited(
    db_session: Session, app: FastAPI
) -> None:
    """changes.csv lists lead, email, field, old and new; formulas are neutralised; audited."""
    rep = make_user(db_session)
    import_file, report = _finished_import(db_session, rep)
    person = make_person(db_session, first_name="=HYPERLINK", last_name="Doe")
    make_person_email(db_session, person=person, address="doe@acme.example")
    make_import_change(
        db_session,
        report=report,
        person=person,
        changes=[
            {"field": "title", "old": "-old", "new": "New"},
            {"field": "city", "old": None, "new": "Cork"},
        ],
    )

    response = _client(db_session, app, rep).get(f"/imports/{import_file.id}/download/changes.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert f"import-{import_file.id}-changes.csv" in response.headers["content-disposition"]
    rows = _csv_rows(response.text)
    assert rows[0] == ["lead", "email", "field", "old_value", "new_value"]
    assert len(rows) == 3
    assert rows[1][0] == "'=HYPERLINK Doe"
    assert rows[1][3] == "'-old"
    assert rows[2][3] == ""
    (audit,) = _download_audits(db_session)
    assert audit.actor_user_id == rep.id
    assert audit.summary == {"file": "changes", "row_count": 2}
    assert "HYPERLINK" not in str(audit.summary)


# --- failed rows download ----------------------------------------------------------------------


def test_failed_rows_csv_lists_only_rejected_and_quarantined_in_the_original_columns(
    db_session: Session, app: FastAPI
) -> None:
    """The file keeps the uploaded column order, lists rejected and quarantined rows by number."""
    rep = make_user(db_session)
    import_file, _ = _finished_import(db_session, rep)
    _failed_row(
        db_session,
        import_file,
        5,
        RowOutcomeKind.REJECTED,
        "ingest_error",
        {"First Name": "Eve", "Email": "eve@x.example", "Company": "X"},
    )
    _failed_row(
        db_session,
        import_file,
        3,
        RowOutcomeKind.QUARANTINED,
        "personal_email_only",
        {"First Name": "Bob", "Email": "bob@gmail.com", "Company": "Y"},
    )
    _failed_row(
        db_session,
        import_file,
        2,
        RowOutcomeKind.IMPORTED,
        None,
        {"First Name": "Ok", "Email": "ok@x.example", "Company": "Z"},
    )
    _failed_row(
        db_session,
        import_file,
        4,
        RowOutcomeKind.POSSIBLE_DUPLICATE,
        None,
        {"First Name": "Dup", "Email": "dup@x.example", "Company": "Z"},
    )
    make_raw_row(db_session, import_file=import_file, row_number=6)  # no recorded result

    response = _client(db_session, app, rep).get(
        f"/imports/{import_file.id}/download/failed-rows.csv"
    )

    assert response.status_code == 200
    assert _csv_rows(response.text) == [
        ["row_number", "outcome", "reason_code", "First Name", "Email", "Company"],
        ["3", "quarantined", "personal_email_only", "Bob", "bob@gmail.com", "Y"],
        ["5", "rejected", "ingest_error", "Eve", "eve@x.example", "X"],
    ]
    (audit,) = _download_audits(db_session)
    assert audit.summary == {"file": "failed_rows", "row_count": 2}
    assert audit.object_id == str(import_file.id)


def test_failed_rows_csv_neutralises_formulas_in_uploaded_cells(
    db_session: Session, app: FastAPI
) -> None:
    """A malicious uploaded cell such as =cmd(...) comes back as text with a leading apostrophe."""
    rep = make_user(db_session)
    import_file, _ = _finished_import(db_session, rep)
    _failed_row(
        db_session,
        import_file,
        2,
        RowOutcomeKind.REJECTED,
        "ingest_error",
        {"First Name": "=cmd|' /C calc'!A0", "Email": "@evil", "Company": "+1"},
    )

    response = _client(db_session, app, rep).get(
        f"/imports/{import_file.id}/download/failed-rows.csv"
    )

    row = _csv_rows(response.text)[1]
    assert row[3:] == ["'=cmd|' /C calc'!A0", "'@evil", "'+1"]


def test_failed_rows_csv_keeps_columns_the_mapping_cannot_explain(
    db_session: Session, app: FastAPI
) -> None:
    """A key stored on a row but absent from the mapping is appended, so no value is lost."""
    rep = make_user(db_session)
    import_file, _ = _finished_import(db_session, rep)
    _failed_row(
        db_session,
        import_file,
        2,
        RowOutcomeKind.REJECTED,
        "ingest_error",
        {"First Name": "Eve", "Email": "e@x.example", "Zeta": "extra"},
    )

    response = _client(db_session, app, rep).get(
        f"/imports/{import_file.id}/download/failed-rows.csv"
    )

    rows = _csv_rows(response.text)
    assert rows[0] == ["row_number", "outcome", "reason_code", "First Name", "Email", "Zeta"]
    assert rows[1][3:] == ["Eve", "e@x.example", "extra"]


def test_failed_rows_csv_with_no_failures_is_just_the_header(
    db_session: Session, app: FastAPI
) -> None:
    """An import without failed rows downloads a header-only file (and is still audited)."""
    rep = make_user(db_session)
    import_file, _ = _finished_import(db_session, rep)

    response = _client(db_session, app, rep).get(
        f"/imports/{import_file.id}/download/failed-rows.csv"
    )

    assert _csv_rows(response.text) == [["row_number", "outcome", "reason_code"]]
    assert _download_audits(db_session)[0].summary == {"file": "failed_rows", "row_count": 0}
