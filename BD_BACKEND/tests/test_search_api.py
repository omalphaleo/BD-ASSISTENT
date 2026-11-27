"""Tests for the /search endpoints, driven through the real app on a real PostgreSQL (M3-A2).

Needed because the route layer enforces who may search (VIEW_ALL_LEADS, every signed-in BD
user, D-001), turns an invalid FilterSet into 422 without echoing lead data, and returns the
page shape the generated client relies on. Users are synthetic and sign in through a real
session cookie.
"""

from collections.abc import Iterator

import pytest
from csrf_client import CsrfTestClient
from factories.core import make_user
from factories.leads import make_company, make_person
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import services
from app.core.models import User, UserRole
from app.db import get_session
from app.leads.models import LeadStatusFlagType
from app.leads.search import MAX_FILTER_OPTIONS
from app.main import app as real_app

SEARCH_URL = "/search/leads"
OPTIONS_URL = "/search/filter-options"


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


def test_anonymous_user_gets_401(db_session: Session, app: FastAPI) -> None:
    """Without a session the GET route answers 401; the POST route is stopped by CSRF (403)."""
    client = _client(db_session, app, None)

    # POST needs a CSRF token that only a session carries, so the CSRF guard answers first.
    assert client.post(SEARCH_URL, json={}).status_code == 403
    assert client.get(OPTIONS_URL).status_code == 401


@pytest.mark.parametrize("role", list(UserRole))
def test_every_signed_in_role_can_search(db_session: Session, app: FastAPI, role: UserRole) -> None:
    """Reps, managers and admins all see every lead (D-001, D-026): 200 for each role."""
    user = make_user(db_session, role=role)
    person = make_person(db_session, first_name="Visible")
    client = _client(db_session, app, user)

    response = client.post(SEARCH_URL, json={})

    assert response.status_code == 200
    assert str(person.id) in {row["person_id"] for row in response.json()["items"]}


def test_search_returns_the_page_shape(db_session: Session, app: FastAPI) -> None:
    """The response has items, total, limit and offset, and the row carries the agreed fields."""
    company = make_company(db_session, industry="Banking")
    person = make_person(db_session, company_id=company.id, title="CFO")
    client = _client(db_session, app, make_user(db_session))

    body = client.post(
        SEARCH_URL, json={"filters": {"industries": ["banking"]}, "limit": 10, "offset": 0}
    ).json()

    assert (body["total"], body["limit"], body["offset"]) == (1, 10, 0)
    [row] = body["items"]
    assert row["person_id"] == str(person.id) and row["title"] == "CFO"
    assert row["company"]["industry"] == "Banking"
    assert set(row) >= {"primary_email", "owner", "flags", "badges", "last_contacted_at"}


def test_unknown_filter_field_is_422(db_session: Session, app: FastAPI) -> None:
    """A field FilterSet does not declare is rejected with 422, not ignored."""
    client = _client(db_session, app, make_user(db_session))

    response = client.post(SEARCH_URL, json={"filters": {"salary": 5}})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"filters": {"eligible_only": True, "show_opted_out": True}},
        {"filters": {"revenue_min": 10, "revenue_max": 1}},
        {"filters": {"flags_include": ["partner"], "flags_exclude": ["partner"]}},
        {"sort": "salary"},
        {"limit": 0},
        {"limit": 1000},
        {"offset": -5},
        {"unknown_top_level": 1},
    ],
)
def test_invalid_requests_are_422(db_session: Session, app: FastAPI, body: dict) -> None:
    """Contradictory filters, an unsupported sort, bad paging or an extra field: 422."""
    client = _client(db_session, app, make_user(db_session))

    assert client.post(SEARCH_URL, json=body).status_code == 422


def test_filter_options_lists_real_values_and_fixed_lists(
    db_session: Session, app: FastAPI
) -> None:
    """Options come from the data (case-deduplicated) plus the fixed size bands and flags."""
    make_company(
        db_session,
        industry="OptionsTest Industry",
        hq_country="Zedland",
        technologies=["optionstest-tech"],
        latest_funding_round_type="OptionsTest Round",
    )
    make_company(db_session, industry="optionstest industry")
    make_person(db_session, country="zedland", state="Zed State")
    client = _client(db_session, app, make_user(db_session))

    body = client.get(OPTIONS_URL).json()

    assert sum(v.lower() == "optionstest industry" for v in body["industries"]) == 1
    assert sum(v.lower() == "zedland" for v in body["countries"]) == 1
    assert "Zed State" in body["states"]
    assert "optionstest-tech" in body["technologies"]
    assert "OptionsTest Round" in body["funding_stages"]
    assert body["size_bands"] == ["smb", "mid_market", "enterprise"]
    assert set(body["flags"]) == {flag.value for flag in LeadStatusFlagType}


def test_filter_options_are_capped_and_report_truncation(
    db_session: Session, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a list is longer than the cap it is cut and its name appears in `truncated`."""
    monkeypatch.setattr("app.leads.search.MAX_FILTER_OPTIONS", 2)
    for name in ("Cap A", "Cap B", "Cap C"):
        make_company(db_session, industry=name)
    client = _client(db_session, app, make_user(db_session))

    body = client.get(OPTIONS_URL).json()

    assert len(body["industries"]) == 2 and "industries" in body["truncated"]
    assert MAX_FILTER_OPTIONS == 500  # the real cap is unchanged outside this test
