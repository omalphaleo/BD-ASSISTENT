"""Tests for the /segments endpoints, driven through the real app on a real PostgreSQL (M3-A4).

Needed because saved segments carry the object-level rules of D-098: private by default, visible
to the team only when shared, changed or deleted only by the owner (an admin may also clean up a
segment that has no owner), and every write audited without the saved filter values. Users are
synthetic and sign in through a real session cookie.
"""

import uuid
from collections.abc import Iterator

import pytest
from csrf_client import CsrfTestClient
from factories.core import make_user
from factories.search import make_owned_segment
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.config import get_settings
from app.core import services
from app.core.models import User, UserRole
from app.db import get_session
from app.leads.models import Segment, SegmentVisibility
from app.main import app as real_app

SEGMENTS_URL = "/segments"
# A search term that must never appear in an audit row.
SECRET_TERM = "confidential-title-term"


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


def _audit_rows(session: Session, action: str) -> list[AuditLog]:
    """Every audit row of one action, oldest first."""
    return list(
        session.scalars(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.occurred_at)
        )
    )


def test_anonymous_user_gets_401(db_session: Session, app: FastAPI) -> None:
    """Without a session the list answers 401; a write is stopped first by CSRF (403)."""
    client = _client(db_session, app, None)

    assert client.get(SEGMENTS_URL).status_code == 401
    assert client.post(SEGMENTS_URL, json={"name": "x", "filters": {}}).status_code == 403


def test_create_is_private_by_default_and_round_trips_filters(
    db_session: Session, app: FastAPI
) -> None:
    """A new segment is private, owned by the caller, and returns the filters it was saved with."""
    rep = make_user(db_session)
    client = _client(db_session, app, rep)

    response = client.post(
        SEGMENTS_URL,
        json={"name": "  Pharma CFOs  ", "filters": {"titles": ["CFO"], "industries": ["Pharma"]}},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Pharma CFOs"  # trimmed
    assert body["visibility"] == "private"
    assert body["owner"] == {"id": str(rep.id), "email": rep.email}
    assert body["can_edit"] is True
    assert body["filters_valid"] is True
    assert body["filters"]["titles"] == ["CFO"]
    assert body["filters"]["industries"] == ["Pharma"]


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "x", "filters": {"not_a_filter": 1}},  # unknown filter field
        {"name": "x", "filters": {"eligible_only": True, "show_opted_out": True}},  # contradiction
        {"name": "   ", "filters": {}},  # blank name
        {"name": "n" * 256, "filters": {}},  # name over the column length
        {"name": "x", "filters": {}, "owner_id": str(uuid.uuid4())},  # extra field
    ],
)
def test_create_rejects_invalid_input(
    db_session: Session, app: FastAPI, payload: dict[str, object]
) -> None:
    """Bad filters, a blank or oversize name or an extra field answer 422 and save nothing."""
    client = _client(db_session, app, make_user(db_session))

    assert client.post(SEGMENTS_URL, json=payload).status_code == 422
    assert db_session.scalars(select(Segment)).first() is None


def test_duplicate_names_are_allowed(db_session: Session, app: FastAPI) -> None:
    """Decision 4: the same rep may save two segments with the same name."""
    client = _client(db_session, app, make_user(db_session))

    first = client.post(SEGMENTS_URL, json={"name": "Same", "filters": {}})
    second = client.post(SEGMENTS_URL, json={"name": "Same", "filters": {}})

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


def test_list_shows_own_and_shared_but_never_another_reps_private(
    db_session: Session, app: FastAPI
) -> None:
    """A rep sees own segments (any visibility) and shared ones, not a colleague's private one."""
    me = make_user(db_session)
    colleague = make_user(db_session)
    mine = make_owned_segment(db_session, me, name="Mine private")
    shared = make_owned_segment(db_session, colleague, shared=True, name="Team shared")
    make_owned_segment(db_session, colleague, name="Colleague private")

    items = _client(db_session, app, me).get(SEGMENTS_URL).json()["items"]

    assert {item["id"] for item in items} == {str(mine.id), str(shared.id)}
    by_id = {item["id"]: item for item in items}
    assert by_id[str(mine.id)]["can_edit"] is True
    assert by_id[str(shared.id)]["can_edit"] is False
    assert by_id[str(shared.id)]["owner"]["email"] == colleague.email


def test_list_is_sorted_by_name_ignoring_case(db_session: Session, app: FastAPI) -> None:
    """Segments come back alphabetically, case-insensitive."""
    me = make_user(db_session)
    make_owned_segment(db_session, me, name="banana")
    make_owned_segment(db_session, me, name="Apple")
    make_owned_segment(db_session, me, name="cherry")

    names = [i["name"] for i in _client(db_session, app, me).get(SEGMENTS_URL).json()["items"]]

    assert names == ["Apple", "banana", "cherry"]


def test_segment_with_stale_filters_is_listed_but_flagged(
    db_session: Session, app: FastAPI
) -> None:
    """Decision 5: stored filters that no longer validate give filters_valid=False, no filters."""
    me = make_user(db_session)
    make_owned_segment(db_session, me, name="Old", filters={"removed_field": ["x"]})
    make_owned_segment(db_session, me, name="Fine", filters={"titles": ["CFO"]})

    items = {i["name"]: i for i in _client(db_session, app, me).get(SEGMENTS_URL).json()["items"]}

    assert items["Old"]["filters_valid"] is False
    assert items["Old"]["filters"] is None
    assert items["Fine"]["filters_valid"] is True


def test_owner_can_rename_share_and_unshare(db_session: Session, app: FastAPI) -> None:
    """The owner renames and flips visibility with one PATCH (Decision 1); filters stay put."""
    me = make_user(db_session)
    segment = make_owned_segment(db_session, me, filters={"titles": ["CFO"]})
    client = _client(db_session, app, me)
    url = f"{SEGMENTS_URL}/{segment.id}"

    renamed = client.patch(url, json={"name": "Renamed", "visibility": "shared"})
    unshared = client.patch(url, json={"visibility": "private"})

    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed"
    assert renamed.json()["visibility"] == "shared"
    assert unshared.json()["visibility"] == "private"
    assert unshared.json()["filters"]["titles"] == ["CFO"]


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"filters": {}}, {"name": None}])
def test_update_rejects_empty_or_unsupported_bodies(
    db_session: Session, app: FastAPI, payload: dict[str, object]
) -> None:
    """An empty PATCH, a blank name or an attempt to change filters is a 422."""
    me = make_user(db_session)
    segment = make_owned_segment(db_session, me)

    response = _client(db_session, app, me).patch(f"{SEGMENTS_URL}/{segment.id}", json=payload)

    assert response.status_code == 422


def test_private_segment_of_someone_else_is_404(db_session: Session, app: FastAPI) -> None:
    """Decision 3: another rep's private segment looks missing for PATCH and DELETE."""
    owner = make_user(db_session)
    segment = make_owned_segment(db_session, owner, name="Secret list")
    other = _client(db_session, app, make_user(db_session))
    url = f"{SEGMENTS_URL}/{segment.id}"

    assert other.patch(url, json={"name": "Hijack"}).status_code == 404
    assert other.delete(url).status_code == 404
    assert other.delete(f"{SEGMENTS_URL}/{uuid.uuid4()}").status_code == 404  # truly missing
    assert db_session.get(Segment, segment.id).name == "Secret list"


def test_shared_segment_of_someone_else_is_403_for_rep_manager_and_admin(
    db_session: Session, app: FastAPI
) -> None:
    """Decision 3 and 2: a visible shared segment with a live owner is 403 for every other role."""
    owner = make_user(db_session)
    segment = make_owned_segment(db_session, owner, shared=True, name="Team list")
    url = f"{SEGMENTS_URL}/{segment.id}"

    for role in (UserRole.REP, UserRole.MANAGER, UserRole.ADMIN):
        client = _client(db_session, app, make_user(db_session, role=role))
        assert client.patch(url, json={"name": "Hijack"}).status_code == 403
        assert client.delete(url).status_code == 403

    assert db_session.get(Segment, segment.id).name == "Team list"


def test_admin_can_manage_an_ownerless_segment_but_a_rep_cannot(
    db_session: Session, app: FastAPI
) -> None:
    """Decision 2: with no owner, an admin may rename and delete it; a rep still may not."""
    shared = make_owned_segment(db_session, None, shared=True, name="Orphan shared")
    private = make_owned_segment(db_session, None, name="Orphan private")
    rep = _client(db_session, app, make_user(db_session))
    admin = _client(db_session, app, make_user(db_session, role=UserRole.ADMIN))

    assert rep.patch(f"{SEGMENTS_URL}/{shared.id}", json={"name": "No"}).status_code == 403
    assert rep.delete(f"{SEGMENTS_URL}/{private.id}").status_code == 404  # invisible to a rep
    admin_ids = {i["id"] for i in admin.get(SEGMENTS_URL).json()["items"]}
    assert admin_ids == {str(shared.id), str(private.id)}
    assert admin.patch(f"{SEGMENTS_URL}/{shared.id}", json={"name": "Fixed"}).status_code == 200
    assert admin.delete(f"{SEGMENTS_URL}/{shared.id}").status_code == 204
    assert admin.delete(f"{SEGMENTS_URL}/{private.id}").status_code == 204


def test_owner_can_delete_and_it_is_gone(db_session: Session, app: FastAPI) -> None:
    """DELETE answers 204 and the segment disappears from the list."""
    me = make_user(db_session)
    segment = make_owned_segment(db_session, me)
    client = _client(db_session, app, me)

    assert client.delete(f"{SEGMENTS_URL}/{segment.id}").status_code == 204
    assert client.get(SEGMENTS_URL).json()["items"] == []


def test_each_write_is_audited_without_filter_values(db_session: Session, app: FastAPI) -> None:
    """Create, update and delete each add one audit row; none of them holds the filter terms."""
    me = make_user(db_session)
    client = _client(db_session, app, me)

    created = client.post(
        SEGMENTS_URL, json={"name": "Audited", "filters": {"titles": [SECRET_TERM]}}
    ).json()
    url = f"{SEGMENTS_URL}/{created['id']}"
    client.patch(url, json={"name": "Audited 2", "visibility": "shared"})
    client.delete(url)

    [made] = _audit_rows(db_session, "segment.created")
    [changed] = _audit_rows(db_session, "segment.updated")
    [removed] = _audit_rows(db_session, "segment.deleted")
    assert made.actor_user_id == me.id
    assert made.object_type == "segment"
    assert made.object_id == created["id"]
    assert changed.summary == {
        "name": "Audited 2",
        "visibility": "shared",
        "changed": [
            "name",
            "visibility",
        ],
    }
    assert removed.summary == {"name": "Audited 2", "visibility": "shared"}
    for row in (made, changed, removed):
        assert SECRET_TERM not in str(row.summary)


def test_update_that_changes_nothing_writes_no_audit_row(db_session: Session, app: FastAPI) -> None:
    """Repeating the current name and visibility is accepted but is not audited."""
    me = make_user(db_session)
    segment = make_owned_segment(db_session, me, name="Same")

    response = _client(db_session, app, me).patch(
        f"{SEGMENTS_URL}/{segment.id}",
        json={"name": "Same", "visibility": SegmentVisibility.PRIVATE.value},
    )

    assert response.status_code == 200
    assert _audit_rows(db_session, "segment.updated") == []


def test_write_without_csrf_token_is_rejected(db_session: Session, app: FastAPI) -> None:
    """A signed-in write without the CSRF header is 403 and changes nothing."""
    me = make_user(db_session)
    segment = make_owned_segment(db_session, me)
    plain = TestClient(app)  # no automatic CSRF header
    token, _ = services.create_session(db_session, me)
    plain.cookies.set(get_settings().session_cookie_name, token)

    assert plain.delete(f"{SEGMENTS_URL}/{segment.id}").status_code == 403
    assert db_session.get(Segment, segment.id) is not None
