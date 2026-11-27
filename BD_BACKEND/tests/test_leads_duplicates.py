"""Tests for duplicate review in app.leads.duplicates and the /duplicates routes (M2-B5).

Needed because merging two people is the one place lead data is combined by hand (D-108): the
most recent value must be pre-selected, a blank must never erase, every email and all history
must survive, the absorbed person must leave a snapshot, "not a duplicate" must be remembered
(D-092), and only a manager or admin may decide. Each rule has its own test; the API tests use
the real app with the test's rolled-back session. All data is synthetic.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from csrf_client import CsrfTestClient
from factories.core import make_user
from factories.imports import make_import_file, make_raw_row
from factories.leads import (
    make_lead_event,
    make_lead_note,
    make_lead_status_flag,
    make_person,
    make_person_email,
    make_touch,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.config import get_settings
from app.core import services
from app.core.models import User, UserRole
from app.db import get_session
from app.leads import duplicates
from app.leads.duplicates import (
    DuplicateFieldError,
    DuplicateNotFoundError,
    DuplicateNotOpenError,
    DuplicateSurvivorError,
)
from app.leads.matching import record_possible_duplicate
from app.leads.models import (
    DuplicateCandidate,
    DuplicateStatus,
    LeadEvent,
    LeadNote,
    LeadStatusFlag,
    MergeRecord,
    Person,
    PersonEmail,
    Touch,
)
from app.main import app as real_app

BASE_URL = "/duplicates"
OLD = datetime(2026, 1, 1, tzinfo=UTC)
NEW = datetime(2026, 6, 1, tzinfo=UTC)


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


def _manager(session: Session) -> User:
    """A synthetic manager."""
    return make_user(session, role=UserRole.MANAGER)


def _pair(
    session: Session,
    first: dict[str, object] | None = None,
    second: dict[str, object] | None = None,
) -> tuple[DuplicateCandidate, Person, Person]:
    """An open pair of two new people: `first` is the older record, `second` the newer."""
    older = make_person(session, updated_at=OLD, **(first or {}))
    newer = make_person(session, updated_at=NEW, **(second or {}))
    candidate = record_possible_duplicate(session, older.id, newer.id)
    assert candidate is not None
    return candidate, older, newer


# --- list, get and the suggested side ------------------------------------------------------


def test_suggestion_prefers_the_more_recent_non_blank_value(db_session: Session) -> None:
    """The newer record's value is pre-selected; a blank there falls back to the older one."""
    candidate, older, newer = _pair(
        db_session, {"title": "Engineer", "city": "Austin"}, {"title": "CTO", "city": None}
    )
    # "a" is whichever person has the smaller id, so translate sides back to people.
    side_of = {candidate.person_a_id: "a", candidate.person_b_id: "b"}

    view = duplicates.get_candidate(db_session, candidate.id)

    assert view.suggested["title"] == side_of[newer.id]
    assert view.suggested["city"] == side_of[older.id]


def test_list_and_get_show_both_people_with_all_addresses(db_session: Session) -> None:
    """A pair shows both people, their company name and every address, primary first."""
    candidate, older, _ = _pair(db_session)
    make_person_email(
        db_session, person=older, address="b@acme.example", normalized_address="b@acme.example"
    )
    make_person_email(
        db_session,
        person=older,
        address="a@acme.example",
        normalized_address="a@acme.example",
        is_primary=True,
    )

    views, total = duplicates.list_candidates(
        db_session, status=DuplicateStatus.OPEN, limit=50, offset=0
    )
    shown = next(v for v in views if v.candidate.id == candidate.id)
    card = shown.person_a if shown.person_a.person.id == older.id else shown.person_b

    assert total >= 1
    assert card.emails == ["a@acme.example", "b@acme.example"]


def test_get_unknown_pair_is_not_found(db_session: Session) -> None:
    """An id that does not exist is reported as not found."""
    with pytest.raises(DuplicateNotFoundError):
        duplicates.get_candidate(db_session, uuid.uuid4())


# --- not a duplicate -----------------------------------------------------------------------


def test_not_a_duplicate_is_recorded_audited_and_remembered(db_session: Session) -> None:
    """The pair is decided, audited, and a later import cannot raise it again (D-092)."""
    candidate, older, newer = _pair(db_session)
    manager = _manager(db_session)

    view = duplicates.mark_not_duplicate(db_session, manager, candidate.id)

    assert view.candidate.status == DuplicateStatus.NOT_DUPLICATE
    assert view.candidate.decided_by == manager.id
    assert view.candidate.decided_at is not None
    assert record_possible_duplicate(db_session, newer.id, older.id) is None
    event = db_session.scalars(
        select(AuditLog).where(
            AuditLog.action == "duplicate.marked_distinct", AuditLog.object_id == str(candidate.id)
        )
    ).one()
    assert event.actor_user_id == manager.id


def test_a_decided_pair_cannot_be_decided_again(db_session: Session) -> None:
    """Marking or merging a pair that was already decided is a conflict."""
    candidate, older, _ = _pair(db_session)
    manager = _manager(db_session)
    duplicates.mark_not_duplicate(db_session, manager, candidate.id)

    with pytest.raises(DuplicateNotOpenError):
        duplicates.mark_not_duplicate(db_session, manager, candidate.id)
    with pytest.raises(DuplicateNotOpenError):
        duplicates.merge_candidate(
            db_session, manager, candidate.id, survivor_id=older.id, values={}
        )


# --- merge ---------------------------------------------------------------------------------


def test_merge_applies_the_reviewers_choice_and_defaults_to_latest(db_session: Session) -> None:
    """A chosen value wins; a field left out gets the most recent value; blanks never erase."""
    candidate, older, newer = _pair(
        db_session,
        {"first_name": "Jane", "title": "Engineer", "city": "Austin", "department": "Eng"},
        {"first_name": "Janet", "title": "CTO", "city": None, "department": None},
    )

    duplicates.merge_candidate(
        db_session,
        _manager(db_session),
        candidate.id,
        survivor_id=older.id,
        values={"first_name": "Jane"},
    )

    survivor = db_session.get(Person, older.id)
    assert survivor is not None
    assert survivor.first_name == "Jane"  # the reviewer's choice
    assert survivor.title == "CTO"  # the newer record's value
    assert survivor.city == "Austin"  # newer is blank: the older value stays
    assert survivor.department == "Eng"
    assert db_session.get(Person, newer.id) is None


def test_merge_keeps_every_email_with_one_primary(db_session: Session) -> None:
    """All addresses of both people survive, the survivor's primary stays, no address repeats."""
    candidate, older, newer = _pair(db_session)
    make_person_email(
        db_session, person=older, normalized_address="keep@acme.example", is_primary=True
    )
    make_person_email(db_session, person=older, normalized_address="same@acme.example")
    make_person_email(
        db_session, person=newer, normalized_address="new@acme.example", is_primary=True
    )
    make_person_email(db_session, person=newer, normalized_address="same@acme.example")

    duplicates.merge_candidate(
        db_session, _manager(db_session), candidate.id, survivor_id=older.id, values={}
    )

    emails = db_session.scalars(select(PersonEmail).where(PersonEmail.person_id == older.id)).all()
    assert sorted(e.normalized_address for e in emails) == [
        "keep@acme.example",
        "new@acme.example",
        "same@acme.example",
    ]
    assert [e.normalized_address for e in emails if e.is_primary] == ["keep@acme.example"]


def test_merge_combines_history_onto_the_survivor(db_session: Session) -> None:
    """Touches, events, notes and flags move to the survivor; a repeated flag is dropped."""
    candidate, older, newer = _pair(db_session)
    make_touch(db_session, person=older)
    make_touch(db_session, person=newer)
    make_lead_event(db_session, person=newer, event_type="note.test")
    make_lead_note(db_session, person=newer)
    make_lead_status_flag(db_session, person=older)  # qualified on both
    make_lead_status_flag(db_session, person=newer)
    make_lead_status_flag(db_session, person=newer, flag_type="partner")

    duplicates.merge_candidate(
        db_session, _manager(db_session), candidate.id, survivor_id=older.id, values={}
    )

    assert len(db_session.scalars(select(Touch).where(Touch.person_id == older.id)).all()) == 2
    assert db_session.scalars(
        select(LeadEvent).where(
            LeadEvent.person_id == older.id, LeadEvent.event_type == "note.test"
        )
    ).all()
    assert (
        len(db_session.scalars(select(LeadNote).where(LeadNote.person_id == older.id)).all()) == 1
    )
    flags = db_session.scalars(
        select(LeadStatusFlag).where(LeadStatusFlag.person_id == older.id)
    ).all()
    assert sorted(flag.flag_type for flag in flags) == ["partner", "qualified"]


def test_merge_writes_a_snapshot_a_timeline_event_and_an_audit_row(db_session: Session) -> None:
    """The MergeRecord holds the absorbed data; the audit row holds ids and field names only."""
    candidate, older, newer = _pair(db_session, second={"first_name": "Secret", "title": "Boss"})
    make_person_email(
        db_session, person=newer, address="s@acme.example", normalized_address="s@acme.example"
    )
    manager = _manager(db_session)

    record = duplicates.merge_candidate(
        db_session, manager, candidate.id, survivor_id=older.id, values={}
    )

    stored = db_session.get(MergeRecord, record.id)
    assert stored is not None
    assert stored.survivor_id == older.id
    assert stored.absorbed_person_id == newer.id
    assert stored.merged_by == manager.id
    assert stored.snapshot["first_name"] == "Secret"  # type: ignore[index]
    assert stored.snapshot["emails"] == ["s@acme.example"]  # type: ignore[index]
    event = db_session.scalars(
        select(LeadEvent).where(
            LeadEvent.person_id == older.id, LeadEvent.event_type == "person.merged"
        )
    ).one()
    assert event.detail["absorbed_person_id"] == str(newer.id)  # type: ignore[index]
    audit = db_session.scalars(
        select(AuditLog).where(
            AuditLog.action == "duplicate.merged", AuditLog.object_id == str(candidate.id)
        )
    ).one()
    assert "Secret" not in str(audit.summary)


def test_merge_combines_contact_dates_and_lists(db_session: Session) -> None:
    """The later contact date wins, bounce is kept if either had it, lists are joined."""
    candidate, older, _ = _pair(
        db_session,
        {"last_contacted_at": OLD, "lists": ["a"], "email_bounced": False},
        {"last_contacted_at": NEW, "lists": ["a", "b"], "email_bounced": True},
    )

    duplicates.merge_candidate(
        db_session, _manager(db_session), candidate.id, survivor_id=older.id, values={}
    )

    survivor = db_session.get(Person, older.id)
    assert survivor is not None
    assert survivor.last_contacted_at == NEW
    assert survivor.lists == ["a", "b"]
    assert survivor.email_bounced


def test_merge_moves_raw_rows_to_the_survivor(db_session: Session) -> None:
    """The absorbed person's raw rows now point at the survivor."""
    candidate, older, newer = _pair(db_session)
    raw_row = make_raw_row(db_session, import_file=make_import_file(db_session), person_id=newer.id)

    duplicates.merge_candidate(
        db_session, _manager(db_session), candidate.id, survivor_id=older.id, values={}
    )

    db_session.refresh(raw_row)
    assert raw_row.person_id == older.id


def test_merge_moves_other_pairs_and_drops_self_pairs(db_session: Session) -> None:
    """A third person paired with the absorbed one is now paired with the survivor."""
    candidate, older, newer = _pair(db_session)
    third = make_person(db_session)
    other_pair = record_possible_duplicate(db_session, newer.id, third.id)
    assert other_pair is not None

    duplicates.merge_candidate(
        db_session, _manager(db_session), candidate.id, survivor_id=older.id, values={}
    )

    moved = db_session.scalars(
        select(DuplicateCandidate).where(DuplicateCandidate.id == other_pair.id)
    ).one()
    assert {moved.person_a_id, moved.person_b_id} == {older.id, third.id}
    assert moved.person_a_id < moved.person_b_id


def test_merged_pair_is_gone_and_cannot_be_merged_twice(db_session: Session) -> None:
    """After a merge the pair no longer exists, so a second merge is not found."""
    candidate, older, _ = _pair(db_session)
    manager = _manager(db_session)
    duplicates.merge_candidate(db_session, manager, candidate.id, survivor_id=older.id, values={})

    with pytest.raises(DuplicateNotFoundError):
        duplicates.merge_candidate(
            db_session, manager, candidate.id, survivor_id=older.id, values={}
        )


def test_merge_rejects_a_survivor_outside_the_pair_and_unknown_fields(db_session: Session) -> None:
    """The survivor must be one of the two; only listed fields may be set."""
    candidate, older, _ = _pair(db_session)
    manager = _manager(db_session)

    with pytest.raises(DuplicateSurvivorError):
        duplicates.merge_candidate(
            db_session, manager, candidate.id, survivor_id=uuid.uuid4(), values={}
        )
    with pytest.raises(DuplicateFieldError):
        duplicates.merge_candidate(
            db_session, manager, candidate.id, survivor_id=older.id, values={"owner_id": "x"}
        )
    assert db_session.get(Person, older.id) is not None


# --- API -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", ""),
        ("get", f"/{uuid.uuid4()}"),
        ("post", f"/{uuid.uuid4()}/merge"),
        ("post", f"/{uuid.uuid4()}/not-duplicate"),
    ],
)
def test_routes_need_a_session(db_session: Session, app: FastAPI, method: str, path: str) -> None:
    """Without a session cookie nothing is allowed: 401, or 403 from the CSRF check."""
    client = _client(db_session, app, None)

    response = client.request(method.upper(), BASE_URL + path, json={})

    assert response.status_code in ({401} if method == "get" else {401, 403})


def test_a_rep_is_refused_and_manager_and_admin_may_review(
    db_session: Session, app: FastAPI
) -> None:
    """Reps get 403 on every route; managers and admins may list (D-108)."""
    candidate, _, _ = _pair(db_session)
    rep = _client(db_session, app, make_user(db_session, role=UserRole.REP))

    assert rep.get(BASE_URL).status_code == 403
    assert rep.get(f"{BASE_URL}/{candidate.id}").status_code == 403
    assert rep.post(f"{BASE_URL}/{candidate.id}/not-duplicate").status_code == 403
    for role in (UserRole.MANAGER, UserRole.ADMIN):
        client = _client(db_session, app, make_user(db_session, role=role))
        assert client.get(BASE_URL).status_code == 200


def test_get_returns_both_people_and_the_suggestion(db_session: Session, app: FastAPI) -> None:
    """The detail holds both people's fields, their addresses and the suggested side per field."""
    candidate, _, _ = _pair(db_session, {"title": "Engineer"}, {"title": "CTO"})
    client = _client(db_session, app, _manager(db_session))

    body = client.get(f"{BASE_URL}/{candidate.id}").json()

    assert body["status"] == "open"
    titles = {body["person_a"]["fields"]["title"], body["person_b"]["fields"]["title"]}
    assert titles == {"Engineer", "CTO"}
    assert body["suggested"]["title"] in {"a", "b"}
    assert "first_name" in body["person_a"]["fields"]


def test_merge_through_the_api(db_session: Session, app: FastAPI) -> None:
    """POST merge keeps the survivor, returns the record ids and removes the other person."""
    candidate, older, newer = _pair(db_session, {"title": "Engineer"}, {"title": "CTO"})
    client = _client(db_session, app, _manager(db_session))

    response = client.post(
        f"{BASE_URL}/{candidate.id}/merge",
        json={"survivor_id": str(older.id), "values": {"title": "Chief"}},
    )

    assert response.status_code == 200
    assert response.json()["survivor_id"] == str(older.id)
    assert response.json()["absorbed_person_id"] == str(newer.id)
    survivor = db_session.get(Person, older.id)
    assert survivor is not None and survivor.title == "Chief"
    assert client.get(f"{BASE_URL}/{candidate.id}").status_code == 404


def test_not_duplicate_then_conflict_through_the_api(db_session: Session, app: FastAPI) -> None:
    """Marking a pair distinct works once; a second decision answers 409 with a fixed message."""
    candidate, older, _ = _pair(db_session)
    client = _client(db_session, app, _manager(db_session))

    first = client.post(f"{BASE_URL}/{candidate.id}/not-duplicate")
    second = client.post(f"{BASE_URL}/{candidate.id}/not-duplicate")
    merge = client.post(
        f"{BASE_URL}/{candidate.id}/merge", json={"survivor_id": str(older.id), "values": {}}
    )

    assert first.status_code == 200 and first.json()["status"] == "not_duplicate"
    assert second.status_code == 409
    assert second.json() == {"detail": "This pair was already decided."}
    assert merge.status_code == 409
    listed = client.get(BASE_URL, params={"status": "not_duplicate"}).json()
    assert candidate.id in {uuid.UUID(item["id"]) for item in listed["items"]}


def test_api_error_cases(db_session: Session, app: FastAPI) -> None:
    """404 for an unknown pair; 422 for a survivor outside the pair or an unmergeable field."""
    candidate, older, _ = _pair(db_session)
    client = _client(db_session, app, _manager(db_session))

    missing = client.get(f"{BASE_URL}/{uuid.uuid4()}")
    bad_survivor = client.post(
        f"{BASE_URL}/{candidate.id}/merge", json={"survivor_id": str(uuid.uuid4()), "values": {}}
    )
    bad_field = client.post(
        f"{BASE_URL}/{candidate.id}/merge",
        json={"survivor_id": str(older.id), "values": {"owner_id": "x"}},
    )

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Duplicate pair not found"}
    assert bad_survivor.status_code == 422
    assert bad_field.status_code == 422
