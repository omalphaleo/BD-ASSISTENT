"""Tests for assigning the leads of an import whose source owner matched no user (M2-A4, D-075).

Needed because the assignment promises several things that only meet in a real database: the
unmatched leads are derived from the raw rows and the saved owner column, grouped by trimmed
lower-case text; assignment only fills empty owners (D-001); the import must be completed;
only managers and admins may assign (ASSIGN_LEADS); and the audit event holds counts, never
the owner text. The pipeline runs for real with a fake `ingest_row` that creates synthetic
people, so the raw rows and their links are exactly what production writes.
"""

import uuid
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from csrf_client import CsrfTestClient
from factories.core import make_user
from factories.imports import make_column_mapping, make_import_file
from factories.leads import make_person
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
from app.imports.assignment import (
    assign_owner_group,
    list_assignable_users,
    list_unmatched_owners,
)
from app.imports.errors import AssignErrorKind, AssignRejectedError, ImportNotFoundError
from app.imports.models import ImportFile, ImportStatus
from app.imports.parsers import limits_from_settings
from app.imports.pipeline import run_import
from app.imports.raw_keys import original_value_keys
from app.imports.storage import LocalDiskStorage, new_storage_key
from app.leads.contracts import ImportContext, RowOutcome, RowOutcomeKind, SourceRow
from app.leads.models import Person
from app.main import app as real_app

HEADER = ["First Name", "Last Name", "Email", "Owner"]
MAPPING = {0: "first_name", 1: "last_name", 2: "email", 3: "owner_name"}


def _ingest_new_person(db: Session, row: SourceRow, ctx: ImportContext) -> RowOutcome:
    """Stands in for W2's ingest_row: creates one ownerless synthetic person per row."""
    return RowOutcome(kind=RowOutcomeKind.IMPORTED, person_id=make_person(db).id)


@pytest.fixture
def storage(tmp_path: Path) -> LocalDiskStorage:
    """A throwaway upload directory, so tests never touch a real volume."""
    return LocalDiskStorage(tmp_path / "uploads")


@pytest.fixture
def manager(db_session: Session) -> User:
    """A manager: allowed to assign leads and to see every import."""
    return make_user(db_session, role=UserRole.MANAGER)


@pytest.fixture
def rep(db_session: Session) -> User:
    """A rep: the uploader of the imports under test, not allowed to assign."""
    return make_user(db_session)


def _owners(*names: str) -> list[list[str]]:
    """Header plus one synthetic row per owner text (use "" for a row without an owner)."""
    return [HEADER] + [
        [f"First{n}", f"Last{n}", f"person{n}@example.com", owner] for n, owner in enumerate(names)
    ]


def _processed_import(
    db: Session,
    storage: LocalDiskStorage,
    uploader: User,
    rows: list[list[str]],
    *,
    mapping: dict[int, str | None] | None = None,
    headers: list[str] | None = None,
    ingest=_ingest_new_person,
) -> ImportFile:
    """Store the CSV, save a mapping, then run the real pipeline with the fake ingest."""
    key = new_storage_key("csv")
    content = csv_bytes(rows)
    storage.save(key, BytesIO(content))
    import_file = make_import_file(
        db,
        storage_key=key,
        size_bytes=len(content),
        row_count=len(rows) - 1,
        status=ImportStatus.PROCESSING,
        uploaded_by=uploader.id,
    )
    saved_headers = headers if headers is not None else HEADER
    for index, target in (mapping if mapping is not None else MAPPING).items():
        make_column_mapping(
            db,
            import_file=import_file,
            column_index=index,
            source_header=saved_headers[index],
            target_field=target,
        )
    # Commit like the upload and mapping steps do: the job may roll back its open chunk.
    db.commit()
    run_import(
        db,
        import_file.id,
        storage=storage,
        limits=limits_from_settings(get_settings()),
        ingest_row=ingest,
    )
    return import_file


def _groups(db: Session, actor: User, import_file: ImportFile) -> dict[str, int]:
    """The listing as {owner_group: lead_count}."""
    return {g.owner_group: g.lead_count for g in list_unmatched_owners(db, actor, import_file.id)}


def test_unmatched_owners_are_grouped_by_trimmed_lowercase_text_biggest_first(
    db_session: Session, storage: LocalDiskStorage, manager: User, rep: User
) -> None:
    """ "Zed Smith", "zed smith " and " ZED SMITH" are one group; the biggest group is first."""
    import_file = _processed_import(
        db_session,
        storage,
        rep,
        _owners("Zed Smith", "zed smith ", " ZED SMITH", "Bob Lee", "Zed Smith"),
    )

    listing = list_unmatched_owners(db_session, manager, import_file.id)

    assert [(g.owner_group, g.lead_count) for g in listing] == [("zed smith", 4), ("bob lee", 1)]
    # The display name keeps the text as written in the file (trimmed), not the lower-case key.
    assert listing[0].display_name in {"Zed Smith", "ZED SMITH", "zed smith"}


def test_a_matched_owner_is_not_listed(
    db_session: Session, storage: LocalDiskStorage, manager: User, rep: User
) -> None:
    """A row whose owner matched a user was assigned by the pipeline, so it is not unmatched."""
    owner = make_user(db_session, email="jane.doe@example.com")
    import_file = _processed_import(db_session, storage, rep, _owners("Jane Doe", "Nobody Known"))

    assert _groups(db_session, manager, import_file) == {"nobody known": 1}
    owner_ids = db_session.scalars(select(Person.owner_id).where(Person.owner_id.is_not(None)))
    assert owner_ids.all() == [owner.id]


def test_rows_without_an_owner_form_the_blank_group(
    db_session: Session, storage: LocalDiskStorage, manager: User, rep: User
) -> None:
    """An empty owner cell is the "no owner given" group (empty owner_group)."""
    import_file = _processed_import(db_session, storage, rep, _owners("", "  ", "Bob Lee"))

    assert _groups(db_session, manager, import_file) == {"": 2, "bob lee": 1}


def test_an_unmapped_owner_column_puts_every_unowned_lead_in_the_blank_group(
    db_session: Session, storage: LocalDiskStorage, manager: User, rep: User
) -> None:
    """No owner_name column mapped: there is no owner text, so all leads are "no owner given"."""
    mapping: dict[int, str | None] = {0: "first_name", 1: "last_name", 2: "email", 3: None}
    import_file = _processed_import(
        db_session, storage, rep, _owners("Zed", "Bob"), mapping=mapping
    )

    assert _groups(db_session, manager, import_file) == {"": 2}


def test_an_owner_column_without_a_header_is_found_by_position(
    db_session: Session, storage: LocalDiskStorage, manager: User, rep: User
) -> None:
    """A headerless owner column is stored as column_4; the listing must read the same key."""
    headerless = ["First Name", "Last Name", "Email", ""]
    rows = [headerless, *_owners("Zed Smith", "Zed Smith")[1:]]
    import_file = _processed_import(db_session, storage, rep, rows, headers=headerless)

    assert _groups(db_session, manager, import_file) == {"zed smith": 2}


def test_a_lead_that_already_has_an_owner_is_not_listed(
    db_session: Session, storage: LocalDiskStorage, manager: User, rep: User
) -> None:
    """A row merged into a lead that already has an owner never shows as unmatched (D-001)."""
    existing_owner = make_user(db_session)

    def ingest_owned(db: Session, row: SourceRow, ctx: ImportContext) -> RowOutcome:
        """Every row hits an existing lead that is already owned."""
        person = make_person(db, owner_id=existing_owner.id)
        return RowOutcome(kind=RowOutcomeKind.UPDATED, person_id=person.id)

    import_file = _processed_import(
        db_session, storage, rep, _owners("Zed Smith"), ingest=ingest_owned
    )

    assert _groups(db_session, manager, import_file) == {}


def test_the_listing_is_empty_before_the_import_runs(
    db_session: Session, manager: User, rep: User
) -> None:
    """An import still being mapped has no rows, so nothing is unmatched yet."""
    import_file = make_import_file(db_session, uploaded_by=rep.id, status=ImportStatus.MAPPING)

    assert list_unmatched_owners(db_session, manager, import_file.id) == []


def test_assign_gives_the_group_to_the_user_and_audits_counts_only(
    db_session: Session, storage: LocalDiskStorage, manager: User, rep: User
) -> None:
    """Assigning "zed smith" sets the owner of its 3 leads; the audit row has counts, no name."""
    target = make_user(db_session)
    import_file = _processed_import(
        db_session, storage, rep, _owners("Zed Smith", "ZED SMITH", "Zed Smith", "Bob Lee")
    )

    result = assign_owner_group(db_session, manager, import_file.id, "Zed Smith ", target.id)

    # The request text is normalised on the server, so the casing and spaces do not matter.
    assert (result.assigned, result.skipped) == (3, 0)
    assert _groups(db_session, manager, import_file) == {"bob lee": 1}
    owned = db_session.scalars(select(Person).where(Person.owner_id == target.id)).all()
    assert len(owned) == 3
    audit = db_session.scalars(
        select(AuditLog).where(AuditLog.action == AuditAction.IMPORT_OWNER_ASSIGNED.value)
    ).one()
    assert audit.actor_user_id == manager.id
    assert audit.object_id == str(import_file.id)
    assert audit.summary == {
        "assigned_user_id": str(target.id),
        "assigned": 3,
        "skipped": 0,
        "blank_group": False,
    }
    assert "zed" not in str(audit.summary).lower()


def test_assigning_the_blank_group_works_and_is_flagged_in_the_audit(
    db_session: Session, storage: LocalDiskStorage, manager: User, rep: User
) -> None:
    """The empty owner_group assigns the "no owner given" leads and sets blank_group."""
    target = make_user(db_session)
    import_file = _processed_import(db_session, storage, rep, _owners("", "Bob Lee"))

    result = assign_owner_group(db_session, manager, import_file.id, "", target.id)

    assert result.assigned == 1
    audit = db_session.scalars(
        select(AuditLog).where(AuditLog.action == AuditAction.IMPORT_OWNER_ASSIGNED.value)
    ).one()
    assert audit.summary["blank_group"] is True


def test_a_second_assignment_changes_nothing(
    db_session: Session, storage: LocalDiskStorage, manager: User, rep: User
) -> None:
    """Repeating the call (a double click) assigns 0 and reports the 2 owned leads as skipped."""
    first_target, second_target = make_user(db_session), make_user(db_session)
    import_file = _processed_import(db_session, storage, rep, _owners("Zed", "Zed"))
    assign_owner_group(db_session, manager, import_file.id, "zed", first_target.id)

    result = assign_owner_group(db_session, manager, import_file.id, "zed", second_target.id)

    assert (result.assigned, result.skipped) == (0, 2)
    owners = set(db_session.scalars(select(Person.owner_id).where(Person.owner_id.is_not(None))))
    assert owners == {first_target.id}


def test_a_lead_owned_in_the_meantime_is_skipped_not_overwritten(
    db_session: Session, storage: LocalDiskStorage, manager: User, rep: User
) -> None:
    """One of two leads got an owner elsewhere: only the other is assigned, one is skipped."""
    target, other_owner = make_user(db_session), make_user(db_session)
    import_file = _processed_import(db_session, storage, rep, _owners("Zed", "Zed"))
    person = db_session.scalars(select(Person).order_by(Person.id)).first()
    person.owner_id = other_owner.id
    db_session.flush()

    result = assign_owner_group(db_session, manager, import_file.id, "zed", target.id)

    assert (result.assigned, result.skipped) == (1, 1)
    db_session.refresh(person)
    assert person.owner_id == other_owner.id


def test_assign_is_refused_until_the_import_is_completed(
    db_session: Session, manager: User, rep: User
) -> None:
    """While the job is still PROCESSING, assigning raises NOT_ASSIGNABLE_YET."""
    import_file = make_import_file(db_session, uploaded_by=rep.id, status=ImportStatus.PROCESSING)

    with pytest.raises(AssignRejectedError) as raised:
        assign_owner_group(db_session, manager, import_file.id, "zed", make_user(db_session).id)

    assert raised.value.kind is AssignErrorKind.NOT_ASSIGNABLE_YET


@pytest.mark.parametrize("active", [False, None])
def test_assign_refuses_an_inactive_or_unknown_user(
    db_session: Session, storage: LocalDiskStorage, manager: User, rep: User, active: bool | None
) -> None:
    """A deactivated user and a random ID are both refused as USER_NOT_ASSIGNABLE."""
    import_file = _processed_import(db_session, storage, rep, _owners("Zed"))
    user_id = uuid.uuid4() if active is None else make_user(db_session, is_active=active).id

    with pytest.raises(AssignRejectedError) as raised:
        assign_owner_group(db_session, manager, import_file.id, "zed", user_id)

    assert raised.value.kind is AssignErrorKind.USER_NOT_ASSIGNABLE
    assert _groups(db_session, manager, import_file) == {"zed": 1}


def test_a_rep_cannot_reach_another_reps_import(
    db_session: Session, storage: LocalDiskStorage, rep: User
) -> None:
    """The service applies the visibility rule too: a rep gets "not found" for someone else's."""
    import_file = _processed_import(db_session, storage, rep, _owners("Zed"))
    stranger = make_user(db_session)

    with pytest.raises(ImportNotFoundError):
        list_unmatched_owners(db_session, stranger, import_file.id)
    with pytest.raises(ImportNotFoundError):
        assign_owner_group(db_session, stranger, import_file.id, "zed", rep.id)


def test_assignable_users_lists_only_active_users_by_email(db_session: Session) -> None:
    """Deactivated users are left out and the rest are ordered by email."""
    active_b = make_user(db_session, email="b@example.com")
    active_a = make_user(db_session, email="a@example.com")
    make_user(db_session, email="c@example.com", is_active=False)

    emails = [u.email for u in list_assignable_users(db_session)]

    assert emails == [active_a.email, active_b.email]


def test_original_value_keys_use_the_header_or_the_position() -> None:
    """Empty and repeated headers fall back to column_N; short header rows are padded."""
    assert original_value_keys(["Email", "", "Email"], 4) == [
        "Email",
        "column_2",
        "column_3",
        "column_4",
    ]


# --- HTTP layer -------------------------------------------------------------------------------


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


def test_routes_refuse_a_rep_with_403(
    db_session: Session, app: FastAPI, storage: LocalDiskStorage, rep: User
) -> None:
    """ASSIGN_LEADS is manager-up: a rep, even the uploader, gets 403 on all three routes."""
    import_file = _processed_import(db_session, storage, rep, _owners("Zed"))
    client = _client(db_session, app, rep)

    assert client.get("/imports/assignable-users").status_code == 403
    assert client.get(f"/imports/{import_file.id}/unmatched-owners").status_code == 403
    body = {"owner_group": "zed", "user_id": str(rep.id)}
    assert client.post(f"/imports/{import_file.id}/assign-owner", json=body).status_code == 403


def test_a_manager_lists_and_assigns_through_the_api(
    db_session: Session, app: FastAPI, storage: LocalDiskStorage, manager: User, rep: User
) -> None:
    """Manager flow: pick a user from assignable-users, list the groups, assign one, list again."""
    target = make_user(db_session, email="target@example.com")
    import_file = _processed_import(db_session, storage, rep, _owners("Zed Smith", "Zed Smith", ""))
    client = _client(db_session, app, manager)

    users = client.get("/imports/assignable-users")
    listing = client.get(f"/imports/{import_file.id}/unmatched-owners")
    assigned = client.post(
        f"/imports/{import_file.id}/assign-owner",
        json={"owner_group": "zed smith", "user_id": str(target.id)},
    )
    after = client.get(f"/imports/{import_file.id}/unmatched-owners")

    assert users.status_code == 200
    assert {"id": str(target.id), "email": "target@example.com"} in users.json()
    assert [(g["owner_group"], g["lead_count"], g["is_blank"]) for g in listing.json()] == [
        ("zed smith", 2, False),
        ("", 1, True),
    ]
    assert assigned.status_code == 200
    assert assigned.json() == {"assigned": 2, "skipped": 0}
    assert [g["owner_group"] for g in after.json()] == [""]


def test_the_api_answers_404_409_and_422(
    db_session: Session, app: FastAPI, storage: LocalDiskStorage, manager: User, rep: User
) -> None:
    """Unknown import 404, not completed 409 with a code, inactive user 422 with a code."""
    client = _client(db_session, app, manager)
    missing = uuid.uuid4()
    processing = make_import_file(db_session, uploaded_by=rep.id, status=ImportStatus.PROCESSING)
    done = _processed_import(db_session, storage, rep, _owners("Zed"))
    inactive = make_user(db_session, is_active=False)

    not_found = client.post(
        f"/imports/{missing}/assign-owner", json={"owner_group": "", "user_id": str(rep.id)}
    )
    too_early = client.post(
        f"/imports/{processing.id}/assign-owner", json={"owner_group": "", "user_id": str(rep.id)}
    )
    bad_user = client.post(
        f"/imports/{done.id}/assign-owner", json={"owner_group": "zed", "user_id": str(inactive.id)}
    )

    assert not_found.status_code == 404
    assert (too_early.status_code, too_early.json()["code"]) == (409, "not_assignable_yet")
    assert (bad_user.status_code, bad_user.json()["code"]) == (422, "user_not_assignable")
