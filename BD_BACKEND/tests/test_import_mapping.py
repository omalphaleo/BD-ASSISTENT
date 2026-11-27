"""Tests for the mapping, profile, preview and estimate endpoints on a real PostgreSQL database.

Needed because M2-A2's rules meet here: a mapping is suggested for Apollo and for other sources
by header name (D-040), a missing or wrong header can be fixed (D-049), only the uploader
changes an import, only admins save a mapping as a profile default, a mandatory field with no
column blocks the start (D-069) without rejecting the file (D-068), and nothing is written by
the preview or the estimate. They drive the real app with synthetic users and files.
"""

import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from csrf_client import CsrfTestClient
from fastapi import FastAPI
from fastapi.testclient import TestClient
from import_files import csv_bytes, xlsx_bytes
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.audit.services import AuditAction
from app.config import get_settings
from app.core import services
from app.core.models import User, UserRole
from app.db import get_session
from app.imports.models import ColumnMapping, ImportFile, ImportStatus, SourceProfile
from app.imports.storage import LocalDiskStorage, get_file_storage
from app.main import app as real_app

# Synthetic Apollo-style file: first name has NO header (the manual-export case of D-049).
APOLLO_ROWS = [
    ["", "Last Name", "Email", "Title", "# Employees", "Email Sent", "Last Contacted"],
    ["Ada", "Lovelace", "ada@example.com", "CTO", "1,200", "yes", "2026-03-04"],
    ["Alan", "Turing", "alan@example.com", "Engineer", "many", "maybe", "04/03/2026"],
    ["", "Hopper", "grace@example.com", "Admiral", "50", "no", ""],
]
# A different provider: other header names, semicolon-separated.
OTHER_ROWS = [
    ["E-mail Address", "Given Name", "Surname", "Company", "Mystery"],
    ["linus@example.com", "Linus", "Torvalds", "Example Org", "x"],
]


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


def _make_user(session: Session, role: UserRole, name: str | None = None) -> User:
    """Insert a synthetic active user (a placeholder hash is enough: no login happens)."""
    user = User(
        email=f"{name or role.value}@example.com", password_hash="not-a-real-hash", role=role
    )
    session.add(user)
    session.flush()
    return user


def _client(session: Session, app: FastAPI, user: User) -> TestClient:
    """A client signed in as the user through a real session cookie."""
    client = CsrfTestClient(app)
    token, _ = services.create_session(session, user)
    client.cookies.set(get_settings().session_cookie_name, token)
    return client


def _upload(client: TestClient, content: bytes, filename: str = "leads.csv") -> uuid.UUID:
    """Upload a file and return the new import's ID."""
    response = client.post(
        "/imports/upload", files={"file": (filename, content, "application/octet-stream")}
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


def _put_mapping(client: TestClient, import_id: uuid.UUID, targets: dict[int, str | None]):
    """PUT a full mapping (column index to target key)."""
    body = {"columns": [{"column_index": i, "target_field": t} for i, t in targets.items()]}
    return client.put(f"/imports/{import_id}/mapping", json=body)


def _add_profile(session: Session, name: str, columns: dict[str, str], active: bool = True):
    """Insert a source profile with saved header defaults."""
    profile = SourceProfile(
        name=name,
        layout="custom",
        is_active=active,
        mapping_defaults={"version": 1, "columns": columns, "formats": {}},
    )
    session.add(profile)
    session.flush()
    return profile


def _actions(session: Session) -> list[str]:
    """Audit actions recorded so far, oldest first."""
    rows = session.execute(select(AuditLog).order_by(AuditLog.occurred_at)).scalars()
    return [row.action for row in rows]


@pytest.fixture
def rep(db_session: Session) -> User:
    """A synthetic rep (the uploader in most tests)."""
    return _make_user(db_session, UserRole.REP)


@pytest.fixture
def rep_client(db_session: Session, app: FastAPI, rep: User) -> TestClient:
    """A client signed in as the rep."""
    return _client(db_session, app, rep)


@pytest.fixture
def apollo_import(rep_client: TestClient) -> uuid.UUID:
    """An uploaded Apollo-style file whose first-name column has no header."""
    return _upload(rep_client, csv_bytes(APOLLO_ROWS))


# --- reference data ---------------------------------------------------------------------------


def test_target_fields_list_the_registry_with_the_two_required_fields(
    rep_client: TestClient,
) -> None:
    """The dropdown source lists every canonical field; only email and first_name are required."""
    fields = rep_client.get("/imports/target-fields").json()
    by_key = {f["key"]: f for f in fields}
    assert {k for k, f in by_key.items() if f["required"]} == {"email", "first_name"}
    assert by_key["secondary_email"]["group"] == "email"
    assert by_key["employee_count"]["value_type"] == "integer"


def test_profile_options_list_only_active_profiles(
    rep_client: TestClient, db_session: Session
) -> None:
    """An uploader may choose active profiles only, and sees no saved mapping content."""
    _add_profile(db_session, "Active one", {"email": "email"})
    _add_profile(db_session, "Retired", {"email": "email"}, active=False)
    options = rep_client.get("/imports/profiles").json()
    assert [o["name"] for o in options] == ["Active one"]
    assert set(options[0]) == {"id", "name", "layout"}


# --- suggesting and saving a mapping ----------------------------------------------------------


def test_apollo_file_gets_a_suggestion_and_the_missing_header_is_flagged(
    rep_client: TestClient, apollo_import: uuid.UUID
) -> None:
    """Known headers are mapped by name; the headerless first column is left for the user."""
    body = rep_client.get(f"/imports/{apollo_import}/mapping").json()
    assert body["is_saved"] is False
    targets = {c["column_index"]: c["target_field"] for c in body["columns"]}
    assert targets == {
        0: None,
        1: "last_name",
        2: "email",
        3: "title",
        4: "employee_count",
        5: "email_sent",
        6: "last_contacted_at",
    }
    assert body["blocking_issues"] == ["first_name_not_mapped"]


def test_fixing_a_missing_header_saves_it_as_reassigned(
    rep_client: TestClient, db_session: Session, apollo_import: uuid.UUID
) -> None:
    """D-049: assigning the headerless column marks it reassigned; the file is not rejected."""
    targets = {0: "first_name", 1: "last_name", 2: "email", 3: "title", 4: "employee_count"}
    response = _put_mapping(rep_client, apollo_import, targets)

    assert response.status_code == 200
    body = response.json()
    assert body["is_saved"] is True
    assert body["blocking_issues"] == []
    by_index = {c["column_index"]: c for c in body["columns"]}
    assert by_index[0]["is_reassigned"] is True
    assert by_index[2]["is_reassigned"] is False
    # Unlisted columns are saved as ignored: the suggestion for them is overridden by omission.
    assert by_index[5]["target_field"] is None
    assert by_index[5]["is_reassigned"] is True
    assert db_session.get(ImportFile, apollo_import).status is ImportStatus.MAPPING
    assert AuditAction.IMPORT_MAPPING_CHANGED.value in _actions(db_session)


def test_saved_mapping_is_returned_instead_of_a_new_suggestion(
    rep_client: TestClient, apollo_import: uuid.UUID
) -> None:
    """Once saved, the same mapping comes back (origin "saved"), ignored columns kept."""
    _put_mapping(rep_client, apollo_import, {0: "first_name", 2: "email"})
    body = rep_client.get(f"/imports/{apollo_import}/mapping").json()
    assert {c["column_index"]: c["target_field"] for c in body["columns"]}[1] is None
    assert body["columns"][0]["origin"] == "saved"


def test_saving_again_replaces_the_earlier_mapping(
    rep_client: TestClient, db_session: Session, apollo_import: uuid.UUID
) -> None:
    """A second save leaves exactly one row per column, with the new targets."""
    _put_mapping(rep_client, apollo_import, {0: "first_name", 2: "email"})
    _put_mapping(rep_client, apollo_import, {0: "last_name", 2: "email"})
    rows = db_session.execute(
        select(ColumnMapping).where(ColumnMapping.import_file_id == apollo_import)
    ).scalars()
    assert {r.column_index: r.target_field for r in rows}[0] == "last_name"
    assert db_session.query(ColumnMapping).filter_by(import_file_id=apollo_import).count() == 7


@pytest.mark.parametrize(
    "targets",
    [
        {0: "first_name", 1: "first_name"},  # one field from two columns
        {0: "not_a_field"},  # unknown field
        {99: "email"},  # column outside the file
    ],
    ids=["duplicate-target", "unknown-field", "bad-column"],
)
def test_invalid_mappings_are_refused_and_nothing_is_saved(
    rep_client: TestClient, db_session: Session, apollo_import: uuid.UUID, targets: dict
) -> None:
    """A mapping W2 could not read is a 422 with a stable code; no rows are written."""
    response = _put_mapping(rep_client, apollo_import, targets)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_mapping"
    assert db_session.query(ColumnMapping).filter_by(import_file_id=apollo_import).count() == 0


def test_a_column_listed_twice_is_refused(rep_client: TestClient, apollo_import: uuid.UUID) -> None:
    """Two entries for one column index are ambiguous and are refused."""
    body = {"columns": [{"column_index": 0, "target_field": "email"}] * 2}
    assert rep_client.put(f"/imports/{apollo_import}/mapping", json=body).status_code == 422


def test_other_provider_headers_are_suggested_without_any_profile(
    rep_client: TestClient,
) -> None:
    """A non-Apollo, semicolon file maps by header name; an unknown header stays unmapped."""
    import_id = _upload(rep_client, csv_bytes(OTHER_ROWS, delimiter=";"))
    body = rep_client.get(f"/imports/{import_id}/mapping").json()
    assert [c["target_field"] for c in body["columns"]] == [
        "email",
        "first_name",
        "last_name",
        "company_name",
        None,
    ]
    assert body["blocking_issues"] == []


# --- who may do what --------------------------------------------------------------------------


def test_only_the_uploader_may_change_the_mapping_but_a_manager_may_view_it(
    db_session: Session, app: FastAPI, rep_client: TestClient, apollo_import: uuid.UUID
) -> None:
    """A manager sees the rep's mapping (200) but cannot save it (409); another rep gets 404."""
    manager = _client(db_session, app, _make_user(db_session, UserRole.MANAGER))
    other_rep = _client(db_session, app, _make_user(db_session, UserRole.REP, "other"))

    assert manager.get(f"/imports/{apollo_import}/mapping").status_code == 200
    refused = _put_mapping(manager, apollo_import, {0: "first_name"})
    assert refused.status_code == 409
    assert refused.json()["code"] == "not_editable"
    assert other_rep.get(f"/imports/{apollo_import}/mapping").status_code == 404
    assert other_rep.get(f"/imports/{apollo_import}/preview").status_code == 404
    assert other_rep.get(f"/imports/{apollo_import}/estimate").status_code == 404


def test_a_mapping_cannot_change_once_processing_has_started(
    rep_client: TestClient, db_session: Session, apollo_import: uuid.UUID
) -> None:
    """After the import left the mapping stage, saving is refused with 409."""
    db_session.get(ImportFile, apollo_import).status = ImportStatus.PROCESSING
    db_session.flush()
    assert _put_mapping(rep_client, apollo_import, {0: "first_name"}).status_code == 409


# --- profile and default country --------------------------------------------------------------


def test_choosing_a_profile_sets_country_and_drives_the_suggestion(
    rep_client: TestClient, db_session: Session, apollo_import: uuid.UUID
) -> None:
    """A profile header default beats the built-in alias; the country is stored (D-078)."""
    profile = _add_profile(db_session, "Mine", {"title": "seniority"})
    response = rep_client.put(
        f"/imports/{apollo_import}/profile",
        json={"source_profile_id": str(profile.id), "default_country": "  India "},
    )

    assert response.status_code == 200
    assert response.json()["default_country"] == "India"
    assert response.json()["source_profile_id"] == str(profile.id)
    body = rep_client.get(f"/imports/{apollo_import}/mapping").json()
    assert {c["column_index"]: c["origin"] for c in body["columns"]}[3] == "profile"
    assert {c["column_index"]: c["target_field"] for c in body["columns"]}[3] == "seniority"


@pytest.mark.parametrize("active", [None, False], ids=["missing", "inactive"])
def test_unknown_or_inactive_profile_is_refused(
    rep_client: TestClient, db_session: Session, apollo_import: uuid.UUID, active: bool | None
) -> None:
    """A profile that does not exist or is switched off cannot be chosen (422)."""
    profile_id = uuid.uuid4()
    if active is not None:
        profile_id = _add_profile(db_session, "Off", {}, active=active).id
    response = rep_client.put(
        f"/imports/{apollo_import}/profile", json={"source_profile_id": str(profile_id)}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "unknown_profile"


def test_matching_profiles_are_only_suggested_never_applied(
    rep_client: TestClient, db_session: Session, apollo_import: uuid.UUID
) -> None:
    """A matching profile is listed, but the import keeps no profile until the user chooses."""
    profile = _add_profile(
        db_session, "Looks right", {"last name": "last_name", "email": "email", "title": "title"}
    )
    body = rep_client.get(f"/imports/{apollo_import}/mapping").json()
    assert [s["source_profile_id"] for s in body["profile_suggestions"]] == [str(profile.id)]
    assert db_session.get(ImportFile, apollo_import).source_profile_id is None


# --- saving a mapping as the profile default --------------------------------------------------


def test_admin_saves_the_mapping_as_profile_defaults_and_the_next_file_uses_them(
    db_session: Session, app: FastAPI, rep_client: TestClient, apollo_import: uuid.UUID
) -> None:
    """The headerless column cannot be remembered; named columns are, merged and audited."""
    admin = _client(db_session, app, _make_user(db_session, UserRole.ADMIN))
    profile = _add_profile(db_session, "Saved", {"zzz": "keywords"})
    _put_mapping(
        rep_client, apollo_import, {0: "first_name", 1: "last_name", 2: "email", 3: "department"}
    )

    response = admin.post(
        f"/imports/{apollo_import}/mapping/save-as-default",
        json={"source_profile_id": str(profile.id)},
    )

    assert response.status_code == 200
    db_session.refresh(profile)
    columns = profile.mapping_defaults["columns"]
    assert columns["title"] == "department"  # learned from the saved mapping
    assert columns["zzz"] == "keywords"  # an earlier default is kept
    assert "" not in columns  # a missing header has no key to remember
    assert AuditAction.SOURCE_PROFILE_UPDATED.value in _actions(db_session)
    # The next file with the same headers now suggests the learned mapping.
    next_import = _upload(
        rep_client, csv_bytes(APOLLO_ROWS[:2] + [["Z", "Z", "z@example.com"] + ["x"] * 4])
    )
    rep_client.put(f"/imports/{next_import}/profile", json={"source_profile_id": str(profile.id)})
    suggested = rep_client.get(f"/imports/{next_import}/mapping").json()["columns"]
    assert suggested[3]["target_field"] == "department"


def test_reps_cannot_save_profile_defaults(
    rep_client: TestClient, db_session: Session, apollo_import: uuid.UUID
) -> None:
    """Saving defaults needs MANAGE_SOURCE_PROFILES (admins): a rep gets 403."""
    profile = _add_profile(db_session, "P", {})
    response = rep_client.post(
        f"/imports/{apollo_import}/mapping/save-as-default",
        json={"source_profile_id": str(profile.id)},
    )
    assert response.status_code == 403


def test_save_as_default_needs_a_saved_mapping(
    db_session: Session, app: FastAPI, apollo_import: uuid.UUID, rep_client: TestClient
) -> None:
    """Nothing saved for the file yet: 409 mapping_not_saved."""
    admin = _client(db_session, app, _make_user(db_session, UserRole.ADMIN))
    profile = _add_profile(db_session, "P", {})
    response = admin.post(
        f"/imports/{apollo_import}/mapping/save-as-default",
        json={"source_profile_id": str(profile.id)},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "mapping_not_saved"


# --- preview and estimate ---------------------------------------------------------------------


def test_preview_and_estimate_need_a_saved_mapping(
    rep_client: TestClient, apollo_import: uuid.UUID
) -> None:
    """Before the mapping is saved both answer 409 mapping_not_saved."""
    for path in ("preview", "estimate"):
        response = rep_client.get(f"/imports/{apollo_import}/{path}")
        assert response.status_code == 409
        assert response.json()["code"] == "mapping_not_saved"


def test_preview_shows_typed_values_and_unreadable_cells_as_warnings(
    rep_client: TestClient, apollo_import: uuid.UUID
) -> None:
    """Rows appear as the pipeline would receive them; bad cells become null plus a warning."""
    _put_mapping(
        rep_client,
        apollo_import,
        {0: "first_name", 2: "email", 4: "employee_count", 5: "email_sent", 6: "last_contacted_at"},
    )
    rows = rep_client.get(f"/imports/{apollo_import}/preview").json()["rows"]

    assert [r["row_number"] for r in rows] == [2, 3, 4]  # row 1 is the header
    assert rows[0]["values"] == {
        "first_name": "Ada",
        "email": "ada@example.com",
        "employee_count": 1200,
        "email_sent": True,
        "last_contacted_at": "2026-03-04T00:00:00",
    }
    assert {(w["field"], w["code"]) for w in rows[1]["warnings"]} == {
        ("employee_count", "not_an_integer"),
        ("email_sent", "not_a_boolean"),
        ("last_contacted_at", "not_a_date"),
    }
    assert rows[1]["values"]["employee_count"] is None
    assert rows[2]["values"]["first_name"] is None  # a blank cell is None without a warning
    assert rows[2]["warnings"] == []


def test_estimate_counts_what_the_file_shows_and_flags_a_blocking_gap(
    rep_client: TestClient, apollo_import: uuid.UUID
) -> None:
    """Rows and gaps are counted; an unmapped mandatory field blocks the start."""
    _put_mapping(rep_client, apollo_import, {1: "last_name", 2: "email", 4: "employee_count"})
    blocked = rep_client.get(f"/imports/{apollo_import}/estimate").json()
    assert blocked["can_start"] is False
    assert blocked["blocking_issues"] == ["first_name_not_mapped"]
    assert blocked["rows_total"] == 3

    _put_mapping(rep_client, apollo_import, {0: "first_name", 2: "email", 4: "employee_count"})
    ready = rep_client.get(f"/imports/{apollo_import}/estimate").json()
    assert ready["can_start"] is True
    assert ready["rows_total"] == 3
    assert ready["rows_without_first_name"] == 1
    assert ready["rows_without_email"] == 0
    assert ready["warning_counts"] == {"employee_count": 1}
    assert {c["column_index"] for c in ready["unmapped_columns"]} == {1, 3, 5, 6}


def test_preview_and_estimate_write_nothing(
    rep_client: TestClient, db_session: Session, apollo_import: uuid.UUID
) -> None:
    """Reading the preview and the estimate adds no audit rows and changes no status."""
    _put_mapping(rep_client, apollo_import, {0: "first_name", 2: "email"})
    before = _actions(db_session)
    rep_client.get(f"/imports/{apollo_import}/preview")
    rep_client.get(f"/imports/{apollo_import}/estimate")
    assert _actions(db_session) == before


def test_xlsx_dates_and_numbers_are_converted_and_a_sheet_must_be_chosen(
    rep_client: TestClient, db_session: Session
) -> None:
    """A two-sheet workbook needs a worksheet first (409); Excel dates and numbers convert."""
    sheet = [
        ["Email", "First Name", "Employees", "Last Contacted"],
        ["a@example.com", "Ann", 15.0, datetime(2026, 5, 6, 7, 8)],
    ]
    import_id = _upload(rep_client, xlsx_bytes({"A": sheet, "B": sheet}), "leads.xlsx")

    refused = rep_client.get(f"/imports/{import_id}/mapping")
    assert refused.status_code == 409
    assert refused.json()["code"] == "worksheet_required"

    assert (
        rep_client.post(f"/imports/{import_id}/worksheet", json={"worksheet": "A"}).status_code
        == 200
    )
    _put_mapping(
        rep_client,
        import_id,
        {0: "email", 1: "first_name", 2: "employee_count", 3: "last_contacted_at"},
    )
    [row] = rep_client.get(f"/imports/{import_id}/preview").json()["rows"]
    assert row["values"]["employee_count"] == 15
    assert row["values"]["last_contacted_at"] == "2026-05-06T07:08:00"
    assert row["warnings"] == []
