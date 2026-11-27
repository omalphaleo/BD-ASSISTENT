"""Tests for POST /search/nl-interpret through the real app on a real PostgreSQL (M3-A6).

Needed because the route decides who may use NL search (VIEW_ALL_LEADS, every signed-in BD
user), what the user sees when AI is off or misbehaves (503 or 502 with a plain message, never
a stack trace), and that nothing runs a search: it only proposes filters. The provider is the
scripted FakeProvider plugged in through the same dependency the real one uses.
"""

from collections.abc import Iterator

import pytest
from csrf_client import CsrfTestClient
from factories.core import make_user
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.fake import FakeProvider, server_error
from app.audit.models import AuditLog
from app.audit.services import AuditAction
from app.config import get_settings
from app.core import services
from app.core.models import User, UserRole
from app.db import get_session
from app.leads.search_api import get_ai_provider
from app.main import app as real_app

URL = "/search/nl-interpret"
SENTENCE = "CFOs at pharma companies in Karnataka"


@pytest.fixture
def app(db_session: Session) -> Iterator[FastAPI]:
    """The real app wired to the test's rolled-back session; AI is off unless a test plugs it in."""

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


def _use_provider(app: FastAPI, provider: FakeProvider) -> None:
    """Plug the fake in where the route asks for its AI provider."""
    app.dependency_overrides[get_ai_provider] = lambda: provider


def _audits(session: Session) -> list[AuditLog]:
    """The NL audit events written so far."""
    return list(
        session.scalars(
            select(AuditLog).where(AuditLog.action == AuditAction.SEARCH_NL_INTERPRETED.value)
        )
    )


def test_anonymous_request_is_refused(db_session: Session, app: FastAPI) -> None:
    """Without a session the CSRF guard stops the POST (403) and nothing is audited."""
    client = _client(db_session, app, None)

    assert client.post(URL, json={"query": SENTENCE}).status_code == 403
    assert _audits(db_session) == []


@pytest.mark.parametrize("role", list(UserRole))
def test_every_signed_in_role_can_interpret(
    db_session: Session, app: FastAPI, role: UserRole
) -> None:
    """Reps, managers and admins may all use NL search: 200 with the draft filters."""
    _use_provider(app, FakeProvider([{"titles": ["CFO"], "unrecognised_terms": ["pharma"]}]))
    client = _client(db_session, app, make_user(db_session, role=role))

    response = client.post(URL, json={"query": SENTENCE})

    assert response.status_code == 200
    body = response.json()
    assert body["filters"]["titles"] == ["CFO"]
    assert body["unrecognised_terms"] == ["pharma"]
    assert body["dropped_fields"] == []
    assert len(_audits(db_session)) == 1


def test_it_only_proposes_filters(db_session: Session, app: FastAPI) -> None:
    """The response carries filters, not leads: no search runs and no rows are returned."""
    _use_provider(app, FakeProvider([{"titles": ["CFO"]}]))
    client = _client(db_session, app, make_user(db_session))

    body = client.post(URL, json={"query": SENTENCE}).json()

    assert set(body) == {"filters", "dropped_fields", "unrecognised_terms"}


def test_without_a_key_ai_is_unavailable_but_the_app_works(
    db_session: Session, app: FastAPI
) -> None:
    """No GEMINI_API_KEY: 503 with a plain message, and structured search still answers 200."""
    client = _client(db_session, app, make_user(db_session))

    response = client.post(URL, json={"query": SENTENCE})

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()
    assert client.post("/search/leads", json={}).status_code == 200
    assert _audits(db_session) == []


def test_provider_outage_is_503_and_unaudited(db_session: Session, app: FastAPI) -> None:
    """A provider that keeps failing gives 503 without a stack trace, and writes no audit row."""
    _use_provider(app, FakeProvider([server_error()]))
    client = _client(db_session, app, make_user(db_session))

    response = client.post(URL, json={"query": SENTENCE})

    assert response.status_code == 503
    assert "Traceback" not in response.text
    assert _audits(db_session) == []


def test_unusable_answer_is_502(db_session: Session, app: FastAPI) -> None:
    """A model answer that is not valid JSON gives 502 with a plain message and no audit row."""
    _use_provider(app, FakeProvider(["this is not json"]))
    client = _client(db_session, app, make_user(db_session))

    response = client.post(URL, json={"query": SENTENCE})

    assert response.status_code == 502
    assert "this is not json" not in response.text
    assert _audits(db_session) == []


@pytest.mark.parametrize(
    "body",
    [{}, {"query": ""}, {"query": "   "}, {"query": "x" * 501}, {"query": SENTENCE, "extra": 1}],
)
def test_bad_request_bodies_are_422(
    db_session: Session, app: FastAPI, body: dict[str, object]
) -> None:
    """A missing, blank, over-long (above 500 characters) or unknown-field body is a 422."""
    _use_provider(app, FakeProvider([{"titles": ["CFO"]}]))
    client = _client(db_session, app, make_user(db_session))

    assert client.post(URL, json=body).status_code == 422


def test_audit_row_names_the_actor_and_not_the_sentence(db_session: Session, app: FastAPI) -> None:
    """The audit row belongs to the caller and holds no part of the typed sentence."""
    _use_provider(app, FakeProvider([{"titles": ["CFO"]}]))
    user = make_user(db_session)
    client = _client(db_session, app, user)

    client.post(URL, json={"query": "zz-unique-sentence-zz"})

    (audit,) = _audits(db_session)
    assert audit.actor_user_id == user.id
    assert "zz-unique-sentence-zz" not in str(audit.summary)
