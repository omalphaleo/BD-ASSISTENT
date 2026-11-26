"""Tests for the industry and state mapping admin in app.leads.mappings and its routes (M2-B6).

Needed because these mappings decide how every later import is tidied (D-076, D-078): wordings
must be stored lowercase and unique, edits must change only what was sent, every change must be
audited, and only an admin may use the routes (D-104). The API tests use the real app with the
test's rolled-back session. All data is synthetic.
"""

import uuid
from collections.abc import Iterator

import pytest
from csrf_client import CsrfTestClient
from factories.core import make_user
from factories.leads import make_industry_mapping, make_state_mapping
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.config import get_settings
from app.core import services
from app.core.models import User, UserRole
from app.db import get_session
from app.leads import mappings
from app.leads.mappings import MappingExistsError, MappingNotFoundError, MappingValueError
from app.leads.models import IndustryMapping, StateMapping
from app.main import app as real_app

BASE_URL = "/reference-mappings"


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


def _admin(session: Session) -> User:
    """A synthetic admin."""
    return make_user(session, role=UserRole.ADMIN)


# --- service: industries -------------------------------------------------------------------


def test_create_industry_stores_lowercase_trimmed_wording(db_session: Session) -> None:
    """The wording is trimmed and lowercased; the standard industry is kept as typed."""
    row = mappings.create_industry_mapping(
        db_session,
        _admin(db_session),
        source_name="  Software DEV ",
        standard_industry=" Information ",
        naics_sector=" 51 ",
    )

    assert (row.source_name, row.standard_industry, row.naics_sector) == (
        "software dev",
        "Information",
        "51",
    )


def test_create_industry_rejects_a_blank_value(db_session: Session) -> None:
    """A wording or standard industry that is blank after trimming is refused."""
    with pytest.raises(MappingValueError):
        mappings.create_industry_mapping(
            db_session,
            _admin(db_session),
            source_name="  ",
            standard_industry="X",
            naics_sector=None,
        )


def test_create_industry_rejects_a_repeated_wording(db_session: Session) -> None:
    """The same wording cannot map twice, whatever its case."""
    make_industry_mapping(db_session, source_name="software dev")

    with pytest.raises(MappingExistsError):
        mappings.create_industry_mapping(
            db_session,
            _admin(db_session),
            source_name="Software Dev",
            standard_industry="Information",
            naics_sector=None,
        )


def test_update_industry_changes_only_the_fields_sent(db_session: Session) -> None:
    """Only the standard industry changes; the wording and sector stay."""
    row = make_industry_mapping(
        db_session, source_name="saas", standard_industry="Old", naics_sector="51"
    )

    updated = mappings.update_industry_mapping(
        db_session, _admin(db_session), row.id, {"standard_industry": "Information"}
    )

    assert (updated.source_name, updated.standard_industry, updated.naics_sector) == (
        "saas",
        "Information",
        "51",
    )


def test_update_industry_can_clear_the_sector(db_session: Session) -> None:
    """Sending a null sector clears it."""
    row = make_industry_mapping(db_session, naics_sector="51")

    updated = mappings.update_industry_mapping(
        db_session, _admin(db_session), row.id, {"naics_sector": None}
    )

    assert updated.naics_sector is None


def test_update_industry_to_an_existing_wording_is_refused(db_session: Session) -> None:
    """Renaming a mapping onto another mapping's wording is a conflict."""
    make_industry_mapping(db_session, source_name="taken")
    other = make_industry_mapping(db_session, source_name="free")

    with pytest.raises(MappingExistsError):
        mappings.update_industry_mapping(
            db_session, _admin(db_session), other.id, {"source_name": "TAKEN"}
        )


def test_update_unknown_industry_is_not_found(db_session: Session) -> None:
    """An id that does not exist is reported as not found."""
    with pytest.raises(MappingNotFoundError):
        mappings.update_industry_mapping(
            db_session, _admin(db_session), uuid.uuid4(), {"standard_industry": "X"}
        )


def test_list_industries_is_sorted_and_searchable(db_session: Session) -> None:
    """The list is ordered by wording and a search matches text inside it."""
    for name in ("zz widgets", "zz apples", "zz apple pie"):
        make_industry_mapping(db_session, source_name=name)

    rows, total = mappings.list_industry_mappings(db_session, search="ZZ APPLE", limit=10, offset=0)

    assert [row.source_name for row in rows] == ["zz apple pie", "zz apples"]
    assert total == 2


def test_industry_change_is_audited(db_session: Session) -> None:
    """Create and update each write one reference_changed audit row with the kind."""
    admin = _admin(db_session)
    row = mappings.create_industry_mapping(
        db_session, admin, source_name="zz one", standard_industry="A", naics_sector=None
    )
    mappings.update_industry_mapping(db_session, admin, row.id, {"standard_industry": "B"})

    events = db_session.scalars(
        select(AuditLog).where(
            AuditLog.action == "mapping.reference_changed", AuditLog.object_id == str(row.id)
        )
    ).all()
    assert len(events) == 2
    assert {event.summary["kind"] for event in events} == {"industry"}  # type: ignore[index]
    assert {event.actor_user_id for event in events} == {admin.id}


# --- service: states -----------------------------------------------------------------------


def test_same_state_wording_is_allowed_in_another_country(db_session: Session) -> None:
    """Uniqueness is per country and wording, so "ca" may exist for two countries."""
    admin = _admin(db_session)
    mappings.create_state_mapping(
        db_session,
        admin,
        country="United States",
        source_value="ZCA",
        standard_name="California",
        abbreviation="CA",
    )

    other = mappings.create_state_mapping(
        db_session,
        admin,
        country="Canada",
        source_value="zca",
        standard_name="Other",
        abbreviation=None,
    )

    assert other.source_value == "zca"
    with pytest.raises(MappingExistsError):
        mappings.create_state_mapping(
            db_session,
            admin,
            country="Canada",
            source_value="ZCA",
            standard_name="Again",
            abbreviation=None,
        )


def test_update_state_and_list_search(db_session: Session) -> None:
    """A state edit changes only the fields sent; the list is searchable."""
    row = make_state_mapping(
        db_session, country="United States", source_value="zz calif.", standard_name="Old"
    )

    updated = mappings.update_state_mapping(
        db_session,
        _admin(db_session),
        row.id,
        {"standard_name": "California", "abbreviation": "CA"},
    )
    rows, total = mappings.list_state_mappings(db_session, search="zz cal", limit=5, offset=0)

    assert (updated.standard_name, updated.abbreviation, updated.country) == (
        "California",
        "CA",
        "United States",
    )
    assert total == 1 and rows[0].id == row.id


def test_update_state_blank_and_missing(db_session: Session) -> None:
    """A blank required value is refused and an unknown id is not found."""
    row = make_state_mapping(db_session)
    admin = _admin(db_session)

    with pytest.raises(MappingValueError):
        mappings.update_state_mapping(db_session, admin, row.id, {"standard_name": " "})
    with pytest.raises(MappingNotFoundError):
        mappings.update_state_mapping(db_session, admin, uuid.uuid4(), {"standard_name": "X"})


# --- API -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/industries"),
        ("post", "/industries"),
        ("patch", f"/industries/{uuid.uuid4()}"),
        ("get", "/states"),
        ("post", "/states"),
        ("patch", f"/states/{uuid.uuid4()}"),
    ],
)
def test_routes_need_a_session(db_session: Session, app: FastAPI, method: str, path: str) -> None:
    """Without a session cookie nothing is allowed: 401, or 403 from the CSRF check."""
    client = _client(db_session, app, None)

    response = client.request(method.upper(), BASE_URL + path, json={"x": "y"})

    assert response.status_code in ({401} if method == "get" else {401, 403})


@pytest.mark.parametrize("role", [UserRole.REP, UserRole.MANAGER])
def test_only_an_admin_may_use_the_routes(
    db_session: Session, app: FastAPI, role: UserRole
) -> None:
    """A rep or manager gets 403 on a read and on a write (D-104)."""
    client = _client(db_session, app, make_user(db_session, role=role))

    assert client.get(f"{BASE_URL}/industries").status_code == 403
    assert (
        client.post(
            f"{BASE_URL}/industries", json={"source_name": "a", "standard_industry": "b"}
        ).status_code
        == 403
    )


def test_admin_creates_lists_and_edits_an_industry(db_session: Session, app: FastAPI) -> None:
    """An admin adds a mapping (201), finds it in the list and edits it."""
    client = _client(db_session, app, _admin(db_session))

    created = client.post(
        f"{BASE_URL}/industries",
        json={"source_name": "ZZ Gadgets", "standard_industry": "Manufacturing"},
    )
    listing = client.get(f"{BASE_URL}/industries", params={"search": "zz gadg"}).json()
    edited = client.patch(
        f"{BASE_URL}/industries/{created.json()['id']}", json={"naics_sector": "31"}
    )

    assert created.status_code == 201
    assert created.json()["source_name"] == "zz gadgets"
    assert listing["total"] == 1
    assert edited.status_code == 200
    assert edited.json()["naics_sector"] == "31"
    assert db_session.scalars(
        select(IndustryMapping).where(IndustryMapping.source_name == "zz gadgets")
    ).one()


def test_admin_creates_and_edits_a_state(db_session: Session, app: FastAPI) -> None:
    """An admin adds and edits a state mapping."""
    client = _client(db_session, app, _admin(db_session))

    created = client.post(
        f"{BASE_URL}/states",
        json={
            "country": "United States",
            "source_value": "ZZ Cali",
            "standard_name": "California",
            "abbreviation": "CA",
        },
    )
    edited = client.patch(
        f"{BASE_URL}/states/{created.json()['id']}", json={"standard_name": "California (US)"}
    )

    assert created.status_code == 201
    assert edited.json()["standard_name"] == "California (US)"
    assert db_session.scalars(
        select(StateMapping).where(StateMapping.source_value == "zz cali")
    ).one()


def test_api_errors_have_fixed_messages(db_session: Session, app: FastAPI) -> None:
    """409 for a repeated wording, 404 for an unknown id, 422 for blank text or an empty edit."""
    make_industry_mapping(db_session, source_name="zz dup")
    client = _client(db_session, app, _admin(db_session))

    conflict = client.post(
        f"{BASE_URL}/industries", json={"source_name": "ZZ DUP", "standard_industry": "X"}
    )
    missing = client.patch(f"{BASE_URL}/industries/{uuid.uuid4()}", json={"standard_industry": "X"})
    blank = client.post(
        f"{BASE_URL}/industries", json={"source_name": "   ", "standard_industry": "X"}
    )
    empty = client.patch(f"{BASE_URL}/industries/{uuid.uuid4()}", json={})

    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "A mapping for this wording already exists."}
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Mapping not found"}
    assert blank.status_code == 422
    assert empty.status_code == 422
