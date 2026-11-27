"""Role-by-endpoint permission matrix: every route declares access and the guards enforce it.

Needed as the M1 acceptance test for permissions (m1.md A6): a structural check fails when any
route has no declaration, a behavioural check calls one probe route per capability as each role
against a matrix copied by hand from plan.md section 4 (so changing a grant means editing this
file too), and the real /auth routes plus the 401/403 OpenAPI entries are checked.
"""

from collections.abc import Iterator
from typing import Annotated

import pytest
from csrf_client import CsrfTestClient
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import services
from app.core.dependencies import NOT_AUTHENTICATED_DETAIL
from app.core.errors import register_error_handlers
from app.core.models import User, UserRole
from app.core.permissions import (
    PERMISSION_DENIED_DETAIL,
    Permission,
    PermissionGuard,
    PublicRoute,
    RouteDeclaration,
    get_route_declaration,
    iter_api_routes,
    public_route,
    require_permission,
)
from app.db import get_session
from app.main import app as real_app

REP, MANAGER, ADMIN = UserRole.REP.value, UserRole.MANAGER.value, UserRole.ADMIN.value
ALL = {REP, MANAGER, ADMIN}

# Hand-written from plan.md section 4 on purpose: deriving it from PERMISSION_ROLES would only
# test the table against itself. Capability -> roles that may use it.
EXPECTED_MATRIX: dict[str, set[str]] = {
    "view_own_profile": ALL,
    "import_leads": ALL,
    "view_own_leads": ALL,
    "view_all_leads": ALL,
    "assign_leads": {MANAGER, ADMIN},
    "fix_quarantine": ALL,
    "discard_quarantine": ALL,
    "set_lead_status_flag": ALL,
    "manage_source_profiles": {ADMIN},
    "review_duplicates": {MANAGER, ADMIN},
    "export_csv": ALL,
    "download_import_files": ALL,
    "create_segment": ALL,
    "edit_draft": {REP},
    "approve_draft": {REP},
    "view_all_drafts": {MANAGER, ADMIN},
    "add_opt_out": ALL,
    "view_opt_outs": ALL,
    "add_note": ALL,
    "remove_opt_out": {MANAGER, ADMIN},
    "erase_person": {ADMIN},
    "activate_real_sending": {ADMIN},
    "view_content_config": ALL,
    "edit_content_config": {ADMIN},
    "manage_users": {ADMIN},
    "manage_sending_limits": {ADMIN},
    "manage_mailboxes": {ADMIN},
    "manage_test_clock": {ADMIN},
}

# What each real route must declare today: "public" or the capability value.
EXPECTED_REAL_ROUTES = {
    ("GET", "/health"): "public",
    ("POST", "/auth/login"): "public",
    ("POST", "/auth/logout"): "public",
    ("GET", "/auth/me"): "view_own_profile",
    ("GET", "/users/me"): "view_own_profile",
    ("GET", "/users"): "manage_users",
    ("POST", "/users"): "manage_users",
    ("PATCH", "/users/{user_id}"): "manage_users",
    ("POST", "/users/{user_id}/deactivate"): "manage_users",
    ("POST", "/users/{user_id}/reactivate"): "manage_users",
    # M2-A1: import endpoints. Whose imports a user may see is an object-level rule in
    # imports.access (tests/test_import_upload.py), not part of this role matrix.
    ("POST", "/imports/upload"): "import_leads",
    ("GET", "/imports/{import_id}"): "import_leads",
    ("POST", "/imports/{import_id}/worksheet"): "import_leads",
    # M2-B2: quarantine endpoints. Any BD user may list, fix and release (D-107); discard is
    # further limited to the importer, a manager or an admin inside leads.quarantine
    # (tests/test_leads_quarantine.py), which this role matrix does not model.
    ("GET", "/quarantine"): "fix_quarantine",
    ("GET", "/quarantine/{record_id}"): "fix_quarantine",
    ("PATCH", "/quarantine/{record_id}"): "fix_quarantine",
    ("POST", "/quarantine/{record_id}/release"): "fix_quarantine",
    ("POST", "/quarantine/{record_id}/discard"): "discard_quarantine",
    # M2-B5: duplicate review (manager and admin only, D-108).
    ("GET", "/duplicates"): "review_duplicates",
    ("GET", "/duplicates/{candidate_id}"): "review_duplicates",
    ("POST", "/duplicates/{candidate_id}/merge"): "review_duplicates",
    ("POST", "/duplicates/{candidate_id}/not-duplicate"): "review_duplicates",
    # M2-B6: industry and state mappings (admin only, D-104).
    ("GET", "/reference-mappings/industries"): "manage_source_profiles",
    ("POST", "/reference-mappings/industries"): "manage_source_profiles",
    ("PATCH", "/reference-mappings/industries/{mapping_id}"): "manage_source_profiles",
    ("GET", "/reference-mappings/states"): "manage_source_profiles",
    ("POST", "/reference-mappings/states"): "manage_source_profiles",
    ("PATCH", "/reference-mappings/states/{mapping_id}"): "manage_source_profiles",
}


def _override_session(app: FastAPI, session: Session) -> None:
    """Make every dependency in the app use the test's rolled-back database session."""

    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override


def _make_user(session: Session, role: UserRole) -> User:
    """Insert a synthetic active user with the given role."""
    user = User(email=f"{role.value}@example.com", password_hash="not-a-real-hash", role=role)
    session.add(user)
    session.flush()
    return user


def _client_for(session: Session, app: FastAPI, user: User | None) -> TestClient:
    """Return a client for the app, signed in as the user (anonymous when user is None)."""
    client = CsrfTestClient(app)
    if user is not None:
        token, _ = services.create_session(session, user)
        client.cookies.set(get_settings().session_cookie_name, token)
    return client


def _add_probe(app: FastAPI, permission: Permission) -> None:
    """Add GET /probe/<capability>, a stand-in route guarded only by that capability."""

    @app.get(f"/probe/{permission.value}")
    def probe(_user: Annotated[User, Depends(require_permission(permission))]) -> dict[str, str]:
        """Stand-in endpoint: reaching the body proves the guard let the caller through."""
        return {"ok": "yes"}


@pytest.fixture
def probe_app(db_session: Session) -> FastAPI:
    """A throwaway app with one guarded probe route per capability, on the test database."""
    app = FastAPI()
    register_error_handlers(app)
    for permission in Permission:
        _add_probe(app, permission)
    _override_session(app, db_session)
    return app


@pytest.fixture
def real_app_client_factory(db_session: Session) -> Iterator[None]:
    """Point the real app at the test database session; undone after the test."""
    _override_session(real_app, db_session)
    yield
    real_app.dependency_overrides.clear()


def test_expected_matrix_lists_every_capability() -> None:
    """The hand-written matrix and the Permission enum name the same capabilities."""
    assert set(EXPECTED_MATRIX) == {permission.value for permission in Permission}


@pytest.mark.parametrize("permission", list(Permission), ids=lambda p: p.value)
@pytest.mark.parametrize("role", list(UserRole), ids=lambda r: r.value)
def test_role_gets_200_or_403_exactly_as_the_matrix_says(
    probe_app: FastAPI, db_session: Session, permission: Permission, role: UserRole
) -> None:
    """Each role reaches a capability's probe route (200) only if plan.md grants it, else 403."""
    client = _client_for(db_session, probe_app, _make_user(db_session, role))

    response = client.get(f"/probe/{permission.value}")

    if role.value in EXPECTED_MATRIX[permission.value]:
        assert response.status_code == 200
    else:
        assert response.status_code == 403
        assert response.json() == {"detail": PERMISSION_DENIED_DETAIL}


@pytest.mark.parametrize("permission", list(Permission), ids=lambda p: p.value)
def test_anonymous_gets_401_not_403(
    probe_app: FastAPI, db_session: Session, permission: Permission
) -> None:
    """Nobody signed in: 401 for every capability (authentication is checked before 403)."""
    response = _client_for(db_session, probe_app, None).get(f"/probe/{permission.value}")

    assert response.status_code == 401
    assert response.json() == {"detail": NOT_AUTHENTICATED_DETAIL}


def test_disabled_user_gets_401_even_with_a_granted_capability(
    probe_app: FastAPI, db_session: Session
) -> None:
    """A deactivated admin's session is rejected with 401 before any capability check."""
    admin = _make_user(db_session, UserRole.ADMIN)
    client = _client_for(db_session, probe_app, admin)
    db_session.execute(update(User).where(User.id == admin.id).values(is_active=False))

    response = client.get(f"/probe/{Permission.MANAGE_USERS.value}")

    assert response.status_code == 401


def test_every_real_route_declares_exactly_one_access_rule() -> None:
    """Structural: no route in the real app is missing a declaration or declares both kinds."""
    routes = list(iter_api_routes(real_app))
    assert routes, "the real app exposes no API routes; the walk is broken"
    for route in routes:
        assert get_route_declaration(route).is_valid, f"{route.methods} {route.path} undeclared"


def test_real_routes_declare_what_the_matrix_expects() -> None:
    """Role by endpoint: each existing route is public or guarded by the expected capability."""
    declared: dict[tuple[str, str], str] = {}
    for route in iter_api_routes(real_app):
        declaration = get_route_declaration(route)
        label = "public" if declaration.public else declaration.permissions[0].value
        for method in route.methods:
            declared[(method, route.path)] = label

    assert declared == EXPECTED_REAL_ROUTES


def test_a_route_without_a_declaration_is_detected() -> None:
    """The structural check flags a route with no guard, and one that is public and guarded."""
    app = FastAPI()

    @app.get("/forgotten")
    def forgotten() -> None:
        """A route someone forgot to protect."""

    @app.get("/both", dependencies=[Depends(public_route)])
    def both(_user: Annotated[User, Depends(require_permission(Permission.MANAGE_USERS))]) -> None:
        """A contradictory route: declared public and guarded."""

    by_path = {route.path: get_route_declaration(route) for route in iter_api_routes(app)}

    assert by_path["/forgotten"] == RouteDeclaration(public=False, permissions=())
    assert not by_path["/forgotten"].is_valid
    assert not by_path["/both"].is_valid


def test_canary_fastapi_still_exposes_the_guards_on_dependant() -> None:
    """Canary: if a FastAPI upgrade hides guards from route.dependant, fail loudly here."""
    app = FastAPI()

    @app.get("/guarded")
    def guarded(
        _user: Annotated[User, Depends(require_permission(Permission.ERASE_PERSON))],
    ) -> None:
        """Guarded stand-in route."""

    @app.get("/open", dependencies=[Depends(public_route)])
    def open_route() -> None:
        """Public stand-in route."""

    routes = {route.path: route for route in iter_api_routes(app)}
    calls = lambda route: [sub.call for sub in route.dependant.dependencies]  # noqa: E731

    assert any(isinstance(call, PermissionGuard) for call in calls(routes["/guarded"]))
    assert any(isinstance(call, PublicRoute) for call in calls(routes["/open"]))


@pytest.mark.usefixtures("real_app_client_factory")
@pytest.mark.parametrize("role", list(UserRole), ids=lambda r: r.value)
def test_real_auth_me_works_for_every_role(db_session: Session, role: UserRole) -> None:
    """Log in as each role: GET /auth/me returns that user's own role."""
    client = _client_for(db_session, real_app, _make_user(db_session, role))

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["role"] == role.value


@pytest.mark.usefixtures("real_app_client_factory")
def test_real_auth_me_requires_sign_in(db_session: Session) -> None:
    """GET /auth/me with no cookie is 401 with the fixed body."""
    response = _client_for(db_session, real_app, None).get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": NOT_AUTHENTICATED_DETAIL}


def test_openapi_documents_401_and_403_only_on_guarded_routes() -> None:
    """OpenAPI lists 401/403 (ErrorResponse) for /auth/me; public routes get no 401, and a
    403 only where the CSRF check applies (the public POST routes)."""
    schema = real_app.openapi()
    paths = schema["paths"]

    me_responses = paths["/auth/me"]["get"]["responses"]
    assert {"401", "403"} <= set(me_responses)
    expected_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    assert me_responses["403"]["content"]["application/json"]["schema"] == expected_ref
    assert "ErrorResponse" in schema["components"]["schemas"]
    assert not {"401", "403"} & set(paths["/health"]["get"]["responses"])
    for public_path in ("/auth/login", "/auth/logout"):
        responses = paths[public_path]["post"]["responses"]
        assert "401" not in responses
        assert responses["403"]["content"]["application/json"]["schema"] == expected_ref
