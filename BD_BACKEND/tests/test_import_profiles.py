"""Tests for the source profile admin: /source-profiles routes and imports.profiles (M2-A6).

Needed because saved profiles affect every later import of a source (D-049): only admins may
change them (D-104), names stay unique ignoring case, profiles are deactivated rather than
deleted, deactivation warns about unfinished imports without blocking, and every change is
audited. Runs on real PostgreSQL through the app with a rolled-back session; data is synthetic.
"""

import uuid
from collections.abc import Iterator

import pytest
from csrf_client import CsrfTestClient
from factories.core import make_user
from factories.imports import make_import_file, make_source_profile
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
from app.imports.models import ImportStatus
from app.main import app as real_app

# Saved defaults (normalized header -> field key) used by the removal tests.
SAVED_DEFAULTS = {"version": 1, "columns": {"first name": "first_name", "e mail": "email"}}


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


@pytest.fixture
def admin(db_session: Session) -> User:
    """An admin, the only role allowed to manage profiles."""
    return make_user(db_session, role=UserRole.ADMIN)


@pytest.fixture
def admin_client(db_session: Session, app: FastAPI, admin: User) -> TestClient:
    """A client signed in as the admin."""
    return _client(db_session, app, admin)


def _audit_actions(session: Session) -> list[str]:
    """Audit actions written so far, oldest first."""
    return [r.action for r in session.scalars(select(AuditLog).order_by(AuditLog.occurred_at))]


def test_create_returns_an_active_profile_with_no_saved_columns_and_audits(
    db_session: Session, admin_client: TestClient, admin: User
) -> None:
    """Admin creates a profile: 201, trimmed name, active, empty mapping, created_by, audit."""
    response = admin_client.post(
        "/source-profiles", json={"name": "  Apollo  ", "layout": "apollo"}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Apollo"
    assert body["is_active"] is True
    assert body["columns"] == {}
    assert body["saved_column_count"] == 0
    assert AuditAction.SOURCE_PROFILE_CREATED.value in _audit_actions(db_session)


def test_create_with_a_name_differing_only_in_case_is_refused(
    admin_client: TestClient, db_session: Session
) -> None:
    """'apollo' when 'Apollo' exists: 409 duplicate_name (case-insensitive, no migration)."""
    make_source_profile(db_session, name="Apollo")

    response = admin_client.post("/source-profiles", json={"name": "apollo", "layout": "x"})

    assert response.status_code == 409
    assert response.json()["code"] == "duplicate_name"


def test_create_with_a_blank_name_or_long_layout_is_rejected(admin_client: TestClient) -> None:
    """A blank name and a 65-character layout fail validation with 422."""
    assert (
        admin_client.post("/source-profiles", json={"name": "   ", "layout": "x"}).status_code
        == 422
    )
    long_layout = "x" * 65
    assert (
        admin_client.post("/source-profiles", json={"name": "A", "layout": long_layout}).status_code
        == 422
    )


def test_list_includes_inactive_profiles_and_counts_saved_columns(
    admin_client: TestClient, db_session: Session
) -> None:
    """The admin list shows inactive profiles too, with their saved column count."""
    make_source_profile(db_session, name="B off", is_active=False, mapping_defaults=SAVED_DEFAULTS)
    make_source_profile(db_session, name="A on")

    response = admin_client.get("/source-profiles")

    assert response.status_code == 200
    rows = {r["name"]: r for r in response.json()}
    assert rows["B off"]["is_active"] is False
    assert rows["B off"]["saved_column_count"] == 2
    assert rows["A on"]["defaults_valid"] is True


def test_list_flags_a_profile_whose_saved_mapping_is_invalid(
    admin_client: TestClient, db_session: Session
) -> None:
    """Broken stored JSON does not crash the list: defaults_valid is false and the count is 0."""
    make_source_profile(db_session, name="Broken", mapping_defaults={"bad": 1})

    row = next(r for r in admin_client.get("/source-profiles").json() if r["name"] == "Broken")

    assert row["defaults_valid"] is False
    assert row["saved_column_count"] == 0


def test_detail_of_an_unknown_profile_is_404(admin_client: TestClient) -> None:
    """GET of a missing profile answers 404 not_found."""
    response = admin_client.get(f"/source-profiles/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_edit_renames_relabels_and_audits_old_and_new(
    db_session: Session, admin_client: TestClient
) -> None:
    """PATCH changes name and layout; the audit summary records old and new values."""
    profile = make_source_profile(db_session, name="Old", layout="a")

    response = admin_client.patch(
        f"/source-profiles/{profile.id}", json={"name": "New", "layout": "b"}
    )

    assert response.status_code == 200, response.text
    assert (response.json()["name"], response.json()["layout"]) == ("New", "b")
    event = db_session.scalars(
        select(AuditLog).where(AuditLog.action == AuditAction.SOURCE_PROFILE_UPDATED.value)
    ).one()
    assert event.summary["changes"]["name"] == {"old": "Old", "new": "New"}


def test_edit_to_another_profiles_name_ignoring_case_is_refused(
    db_session: Session, admin_client: TestClient
) -> None:
    """Renaming to 'EXISTING' when 'Existing' belongs to another profile: 409."""
    make_source_profile(db_session, name="Existing")
    other = make_source_profile(db_session, name="Other")

    response = admin_client.patch(f"/source-profiles/{other.id}", json={"name": "EXISTING"})

    assert response.status_code == 409


def test_edit_keeping_its_own_name_in_another_case_is_allowed(
    db_session: Session, admin_client: TestClient
) -> None:
    """A profile may change only the case of its own name."""
    profile = make_source_profile(db_session, name="apollo")

    response = admin_client.patch(f"/source-profiles/{profile.id}", json={"name": "Apollo"})

    assert response.status_code == 200
    assert response.json()["name"] == "Apollo"


def test_deactivate_hides_the_profile_from_the_uploader_picker(
    db_session: Session, admin_client: TestClient
) -> None:
    """is_active=false removes it from GET /imports/profiles but keeps it in the admin list."""
    profile = make_source_profile(db_session, name="Retire me")

    assert (
        admin_client.patch(f"/source-profiles/{profile.id}", json={"is_active": False}).status_code
        == 200
    )

    picker = [p["id"] for p in admin_client.get("/imports/profiles").json()]
    assert str(profile.id) not in picker
    assert str(profile.id) in [p["id"] for p in admin_client.get("/source-profiles").json()]


def test_deactivating_a_profile_used_by_an_unfinished_import_warns_but_succeeds(
    db_session: Session, admin_client: TestClient
) -> None:
    """One MAPPING import uses the profile: 200, is_active false and one warning."""
    profile = make_source_profile(db_session)
    make_import_file(db_session, source_profile_id=profile.id, status=ImportStatus.MAPPING)

    response = admin_client.patch(f"/source-profiles/{profile.id}", json={"is_active": False})

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert len(response.json()["warnings"]) == 1


def test_deactivating_a_profile_with_only_finished_imports_has_no_warning(
    db_session: Session, admin_client: TestClient
) -> None:
    """COMPLETED and FAILED imports do not trigger the warning."""
    profile = make_source_profile(db_session)
    make_import_file(db_session, source_profile_id=profile.id, status=ImportStatus.COMPLETED)
    make_import_file(db_session, source_profile_id=profile.id, status=ImportStatus.FAILED)

    response = admin_client.patch(f"/source-profiles/{profile.id}", json={"is_active": False})

    assert response.json()["warnings"] == []


def test_an_edit_that_changes_nothing_writes_no_audit_event(
    db_session: Session, admin_client: TestClient
) -> None:
    """Sending the current values back is a no-op: 200 and no audit row."""
    profile = make_source_profile(db_session, name="Same", layout="a")

    response = admin_client.patch(
        f"/source-profiles/{profile.id}", json={"name": "Same", "layout": "a"}
    )

    assert response.status_code == 200
    assert AuditAction.SOURCE_PROFILE_UPDATED.value not in _audit_actions(db_session)


def test_remove_columns_forgets_the_headers_and_audits(
    db_session: Session, admin_client: TestClient
) -> None:
    """Removing 'First Name' (any case or spacing) leaves only the other saved header."""
    profile = make_source_profile(db_session, mapping_defaults=SAVED_DEFAULTS)

    response = admin_client.post(
        f"/source-profiles/{profile.id}/remove-columns", json={"headers": ["FIRST-name"]}
    )

    assert response.status_code == 200, response.text
    assert response.json()["columns"] == {"e mail": "email"}
    assert AuditAction.SOURCE_PROFILE_UPDATED.value in _audit_actions(db_session)


def test_remove_columns_with_an_unknown_header_changes_nothing(
    db_session: Session, admin_client: TestClient
) -> None:
    """One unknown header among valid ones: 422 unknown_column and the mapping is untouched."""
    profile = make_source_profile(db_session, mapping_defaults=SAVED_DEFAULTS)

    response = admin_client.post(
        f"/source-profiles/{profile.id}/remove-columns",
        json={"headers": ["First Name", "Nope"]},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "unknown_column"
    assert admin_client.get(f"/source-profiles/{profile.id}").json()["saved_column_count"] == 2


def test_remove_columns_of_a_profile_with_invalid_defaults_is_refused(
    db_session: Session, admin_client: TestClient
) -> None:
    """A broken stored mapping cannot be edited: 409 invalid_defaults."""
    profile = make_source_profile(db_session, mapping_defaults={"bad": 1})

    response = admin_client.post(
        f"/source-profiles/{profile.id}/remove-columns", json={"headers": ["x"]}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "invalid_defaults"


@pytest.mark.parametrize("role", [UserRole.REP, UserRole.MANAGER])
def test_non_admins_cannot_use_any_profile_admin_route(
    db_session: Session, app: FastAPI, role: UserRole
) -> None:
    """A rep and a manager get 403 on list, create, edit and remove-columns."""
    client = _client(db_session, app, make_user(db_session, role=role))
    profile = make_source_profile(db_session)

    assert client.get("/source-profiles").status_code == 403
    assert client.post("/source-profiles", json={"name": "N", "layout": "x"}).status_code == 403
    assert client.patch(f"/source-profiles/{profile.id}", json={"name": "Z"}).status_code == 403
    assert (
        client.post(
            f"/source-profiles/{profile.id}/remove-columns", json={"headers": ["a"]}
        ).status_code
        == 403
    )
