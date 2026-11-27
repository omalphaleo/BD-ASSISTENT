"""Tests for the lead CSV export, driven through the real app on a real PostgreSQL (M3-A5).

Needed because the export is how lead data leaves the app (D-087): the file must match what
search shows, carry the agreed columns and eligibility facts, neutralise formula injection, be
open to every BD role, refuse an oversized or invalid request without writing anything, and be
audited with the filter and the row count but never the rows. Users and leads are synthetic.
"""

import csv
import io
from collections.abc import Iterator

import pytest
from csrf_client import CsrfTestClient
from factories.compliance import make_opt_out
from factories.core import make_user
from factories.leads import (
    make_company,
    make_lead_status_flag,
    make_person,
    make_person_email,
)
from factories.search import make_eligible_person
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.audit.services import AuditAction
from app.compliance.eligibility import build_context, check_eligibility
from app.config import get_settings
from app.core import services
from app.core.clock import now
from app.core.models import User, UserRole
from app.db import get_session
from app.leads import export
from app.leads.export import EXPORT_HEADER
from app.leads.models import LeadStatusFlagType
from app.main import app as real_app

EXPORT_URL = "/search/leads/export.csv"
SEARCH_URL = "/search/leads"


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


def _rows(text: str) -> list[dict[str, str]]:
    """Parse the CSV text into one dict per lead, keyed by the header."""
    return list(csv.DictReader(io.StringIO(text)))


def _export(session: Session, app: FastAPI, body: dict[str, object] | None = None) -> list[dict]:
    """Export as a signed-in rep and return the parsed rows (the call must succeed)."""
    response = _client(session, app, make_user(session)).post(EXPORT_URL, json=body or {})
    assert response.status_code == 200, response.text
    return _rows(response.text)


def _export_audits(session: Session) -> list[AuditLog]:
    """The export audit events written so far."""
    return list(
        session.scalars(
            select(AuditLog).where(AuditLog.action == AuditAction.EXPORT_LEADS_DOWNLOADED.value)
        )
    )


def test_anonymous_export_is_refused(db_session: Session, app: FastAPI) -> None:
    """Without a session the CSRF guard stops the POST (403) and nothing is audited."""
    client = _client(db_session, app, None)

    assert client.post(EXPORT_URL, json={}).status_code == 403
    assert _export_audits(db_session) == []


@pytest.mark.parametrize("role", list(UserRole))
def test_every_role_can_export_and_is_audited(
    db_session: Session, app: FastAPI, role: UserRole
) -> None:
    """Reps, managers and admins may export (D-087): 200, CSV headers, one audit event each."""
    user = make_user(db_session, role=role)
    make_eligible_person(db_session)
    client = _client(db_session, app, user)

    response = client.post(EXPORT_URL, json={})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    disposition = response.headers["content-disposition"]
    assert disposition == f'attachment; filename="leads-{now().date().isoformat()}.csv"'
    audits = _export_audits(db_session)
    assert len(audits) == 1
    assert audits[0].actor_user_id == user.id


def test_header_and_row_hold_the_agreed_columns(db_session: Session, app: FastAPI) -> None:
    """The header is the agreed column list and one lead fills person, company, email, owner."""
    owner = make_user(db_session)
    company = make_company(db_session, industry="Banking", employee_count=250, hq_country="India")
    person = make_eligible_person(
        db_session,
        first_name="Asha",
        last_name="Rao",
        title="CFO",
        company_id=company.id,
        owner_id=owner.id,
        city="Pune",
    )
    make_lead_status_flag(db_session, person=person, flag_type=LeadStatusFlagType.PARTNER)

    response = _client(db_session, app, make_user(db_session)).post(EXPORT_URL, json={})

    assert next(csv.reader(io.StringIO(response.text))) == list(EXPORT_HEADER)
    (row,) = _rows(response.text)
    assert row["first_name"] == "Asha"
    assert row["last_name"] == "Rao"
    assert row["title"] == "CFO"
    assert row["city"] == "Pune"
    assert row["company"] == company.name
    assert row["industry"] == "Banking"
    assert row["employee_count"] == "250"
    assert row["company_hq_country"] == "India"
    assert row["email_verification"] == "verified"
    assert row["owner"] == owner.email
    assert row["status_flags"] == "partner"
    assert row["eligible"] == "yes"
    assert row["ineligible_reasons"] == ""
    assert row["opted_out"] == "no"


def test_export_has_the_same_leads_as_search(db_session: Session, app: FastAPI) -> None:
    """For a filter, the export holds exactly the leads search lists, and as many as `total`."""
    bank = make_company(db_session, industry="Banking")
    for _ in range(3):
        make_eligible_person(db_session, company_id=bank.id)
    make_eligible_person(db_session, company_id=make_company(db_session, industry="Retail").id)
    client = _client(db_session, app, make_user(db_session))
    body = {"filters": {"industries": ["banking"]}}

    searched = client.post(SEARCH_URL, json={**body, "limit": 200}).json()
    exported = client.post(EXPORT_URL, json=body)

    assert len(_rows(exported.text)) == searched["total"] == 3
    assert {row["company"] for row in _rows(exported.text)} == {bank.name}


def test_export_follows_the_requested_order(db_session: Session, app: FastAPI) -> None:
    """Sorting by name descending lists the last name first, as search does."""
    for last in ("Adams", "Brown", "Clark"):
        make_eligible_person(db_session, last_name=last)

    rows = _export(db_session, app, {"sort": "name", "direction": "desc"})

    assert [row["last_name"] for row in rows] == ["Clark", "Brown", "Adams"]


def test_default_view_leaves_out_opted_out_leads_and_show_opted_out_adds_them(
    db_session: Session, app: FastAPI
) -> None:
    """Opted-out leads follow the filter: hidden by default, listed (opted_out=yes) on request."""
    make_eligible_person(db_session, first_name="Fine")
    blocked = make_eligible_person(db_session, first_name="Blocked")
    address = make_person_email(db_session, person=blocked).normalized_address
    make_opt_out(db_session, email_normalized=address)

    default_rows = _export(db_session, app)
    shown_rows = _export(db_session, app, {"filters": {"show_opted_out": True}})

    assert [row["first_name"] for row in default_rows] == ["Fine"]
    by_name = {row["first_name"]: row for row in shown_rows}
    assert set(by_name) == {"Fine", "Blocked"}
    assert by_name["Blocked"]["opted_out"] == "yes"
    assert by_name["Blocked"]["eligible"] == "no"
    assert "opted_out" in by_name["Blocked"]["ineligible_reasons"]
    assert by_name["Fine"]["opted_out"] == "no"


def test_eligibility_columns_agree_with_check_eligibility(
    db_session: Session, app: FastAPI
) -> None:
    """Reasons in the file equal check_eligibility for each lead, and unverified is a warning."""
    replied = make_eligible_person(db_session, first_name="Replied", replied_at=now())
    unverified = make_person(db_session, first_name="Unverified")
    make_person_email(
        db_session, person=unverified, verification_status="unverified", is_primary=True
    )
    make_eligible_person(db_session, first_name="Clean")

    rows = {row["first_name"]: row for row in _export(db_session, app)}
    ctx = build_context(db_session)

    for person in (replied, unverified):
        expected = [r.value for r in check_eligibility(db_session, person, ctx).reasons]
        assert rows[person.first_name]["ineligible_reasons"].split(";") == (expected or [""])
    assert rows["Replied"]["ineligible_reasons"] == "replied"
    assert rows["Unverified"]["warnings"] == "unverified_email"
    assert rows["Unverified"]["eligible"] == "yes"
    assert rows["Clean"]["eligible"] == "yes"


@pytest.mark.parametrize("risky", ["=1+1", "+1", "-1", "@SUM(A1)"])
def test_formula_text_in_lead_data_is_neutralised(
    db_session: Session, app: FastAPI, risky: str
) -> None:
    """A lead whose name or title starts with a formula character is written as plain text."""
    make_eligible_person(db_session, first_name=risky, title=risky)

    (row,) = _export(db_session, app)

    assert row["first_name"] == "'" + risky
    assert row["title"] == "'" + risky


def test_audit_event_holds_the_filter_and_count_but_no_lead_data(
    db_session: Session, app: FastAPI
) -> None:
    """The event records filters, sort and row count; names and emails never appear in it."""
    person = make_eligible_person(db_session, first_name="Secretname")
    make_eligible_person(db_session)
    body = {"filters": {"titles": ["cfo"]}, "sort": "company", "direction": "desc"}
    user = make_user(db_session)

    _client(db_session, app, user).post(EXPORT_URL, json=body)

    (audit,) = _export_audits(db_session)
    assert audit.summary is not None
    assert audit.summary["row_count"] == 0
    assert audit.summary["sort"] == "company"
    assert audit.summary["direction"] == "desc"
    assert audit.summary["filters"]["titles"] == ["cfo"]
    stored = str(audit.summary) + str(audit.object_id)
    assert "Secretname" not in stored
    assert person.first_name not in stored


def test_invalid_filters_are_422_and_nothing_is_audited(db_session: Session, app: FastAPI) -> None:
    """An unknown filter field is rejected like search does, with no audit event."""
    client = _client(db_session, app, make_user(db_session))

    response = client.post(EXPORT_URL, json={"filters": {"salary": 1}})

    assert response.status_code == 422
    assert _export_audits(db_session) == []


def test_too_many_matches_are_refused_not_cut(
    db_session: Session, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Over the cap the answer is 422 with the count, no file and no audit event."""
    monkeypatch.setattr(export, "MAX_EXPORT_ROWS", 2)
    for _ in range(3):
        make_eligible_person(db_session)
    client = _client(db_session, app, make_user(db_session))

    response = client.post(EXPORT_URL, json={})

    assert response.status_code == 422
    assert "3 leads match" in response.json()["detail"]
    assert _export_audits(db_session) == []


def test_every_lead_is_exported_across_batches(
    db_session: Session, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a tiny batch size all leads still appear once, so batching loses and repeats none."""
    monkeypatch.setattr(export, "BATCH_SIZE", 2)
    ids = {make_eligible_person(db_session, first_name=f"Lead{i}").first_name for i in range(5)}

    rows = _export(db_session, app)

    assert {row["first_name"] for row in rows} == ids
    assert len(rows) == 5
