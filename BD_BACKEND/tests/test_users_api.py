"""Tests for the /users API and core.user_services on a real PostgreSQL database.

Needed because user management is the first admin-only write API: it must refuse non-admins,
hash passwords, protect the last admin, end sessions on deactivation and audit every change.
They drive the real app.main.app with synthetic users; no real credentials are involved.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.audit.services import AuditAction
from app.config import get_settings
from app.core import services, user_services
from app.core.models import User, UserRole
from app.core.passwords import verify_password
from app.core.permissions import PERMISSION_DENIED_DETAIL
from app.db import get_session
from app.main import app as real_app

STRONG_PASSWORD = "initial-password-123"


@pytest.fixture
def app(db_session: Session) -> Iterator[FastAPI]:
    """The real app wired to the test's rolled-back database session."""

    def override() -> Iterator[Session]:
        yield db_session

    real_app.dependency_overrides[get_session] = override
    yield real_app
    real_app.dependency_overrides.clear()


def _make_user(session: Session, role: UserRole, *, name: str | None = None) -> User:
    """Insert a synthetic active user (a placeholder hash is enough: no login happens)."""
    label = name or role.value
    user = User(email=f"{label}@example.com", password_hash="not-a-real-hash", role=role)
    session.add(user)
    session.flush()
    return user


def _client(session: Session, app: FastAPI, user: User | None) -> TestClient:
    """Return a client signed in as the user through a real session cookie."""
    client = TestClient(app)
    if user is not None:
        token, _ = services.create_session(session, user)
        client.cookies.set(get_settings().session_cookie_name, token)
    return client


def _audit_actions(session: Session) -> list[str]:
    """Return the audit actions recorded so far, oldest first."""
    rows = session.execute(select(AuditLog).order_by(AuditLog.occurred_at)).scalars()
    return [row.action for row in rows]


@pytest.mark.parametrize("role", [UserRole.REP, UserRole.MANAGER], ids=lambda r: r.value)
def test_non_admin_is_refused_on_every_admin_endpoint(
    app: FastAPI, db_session: Session, role: UserRole
) -> None:
    """Rep and manager get the fixed 403 on list, create, edit, deactivate and reactivate."""
    caller = _make_user(db_session, role)
    target = _make_user(db_session, UserRole.REP, name="target")
    client = _client(db_session, app, caller)
    new_user = {"email": "n@example.com", "role": "rep", "password": STRONG_PASSWORD}

    responses = [
        client.get("/users"),
        client.post("/users", json=new_user),
        client.patch(f"/users/{target.id}", json={"role": "manager"}),
        client.post(f"/users/{target.id}/deactivate"),
        client.post(f"/users/{target.id}/reactivate"),
    ]

    for response in responses:
        assert response.status_code == 403
        assert response.json() == {"detail": PERMISSION_DENIED_DETAIL}


def test_anonymous_gets_401(app: FastAPI, db_session: Session) -> None:
    """Nobody signed in: the admin list is 401."""
    assert _client(db_session, app, None).get("/users").status_code == 401


@pytest.mark.parametrize("role", list(UserRole), ids=lambda r: r.value)
def test_every_role_can_read_own_profile(app: FastAPI, db_session: Session, role: UserRole) -> None:
    """GET /users/me returns the caller's own profile, without any password hash."""
    user = _make_user(db_session, role)

    response = _client(db_session, app, user).get("/users/me")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user.id)
    assert body["role"] == role.value
    assert body["is_active"] is True
    assert "password" not in response.text


def test_admin_lists_users_ordered_by_email(app: FastAPI, db_session: Session) -> None:
    """The admin list returns every user sorted by email."""
    admin = _make_user(db_session, UserRole.ADMIN, name="m-admin")
    _make_user(db_session, UserRole.REP, name="z-rep")
    _make_user(db_session, UserRole.REP, name="a-rep")

    response = _client(db_session, app, admin).get("/users")

    assert response.status_code == 200
    emails = [u["email"] for u in response.json()]
    assert emails == sorted(emails)
    assert {"a-rep@example.com", "z-rep@example.com"} <= set(emails)


def test_create_user_hashes_password_normalizes_email_and_audits(
    app: FastAPI, db_session: Session
) -> None:
    """Create: 201, lower-cased email, Argon2 hash that verifies, one user.created audit row."""
    admin = _make_user(db_session, UserRole.ADMIN)

    response = _client(db_session, app, admin).post(
        "/users",
        json={"email": " New.Rep@Example.com ", "role": "rep", "password": STRONG_PASSWORD},
    )

    assert response.status_code == 201
    assert response.json()["email"] == "new.rep@example.com"
    created = db_session.get(User, uuid.UUID(response.json()["id"]))
    assert created.password_hash != STRONG_PASSWORD
    assert verify_password(created.password_hash, STRONG_PASSWORD)
    assert AuditAction.USER_CREATED.value in _audit_actions(db_session)
    audit_row = db_session.execute(
        select(AuditLog).where(AuditLog.action == AuditAction.USER_CREATED.value)
    ).scalar_one()
    assert STRONG_PASSWORD not in str(audit_row.summary)
    assert audit_row.actor_user_id == admin.id


def test_create_user_duplicate_email_is_409_in_any_case(app: FastAPI, db_session: Session) -> None:
    """Creating an email that exists, even in different letter case, is a 409."""
    admin = _make_user(db_session, UserRole.ADMIN)
    _make_user(db_session, UserRole.REP, name="taken")

    response = _client(db_session, app, admin).post(
        "/users", json={"email": "TAKEN@example.com", "role": "rep", "password": STRONG_PASSWORD}
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Email already registered"}


@pytest.mark.parametrize(
    "body",
    [
        {"email": "no-at-sign", "role": "rep", "password": STRONG_PASSWORD},
        {"email": "a@example.com", "role": "rep", "password": "short"},
        {"email": "a@example.com", "role": "superuser", "password": STRONG_PASSWORD},
        {"email": "a@example.com", "role": "rep", "password": STRONG_PASSWORD, "extra": 1},
    ],
    ids=["no-at", "short-password", "bad-role", "extra-field"],
)
def test_create_user_invalid_body_is_422_without_echoing_values(
    app: FastAPI, db_session: Session, body: dict[str, object]
) -> None:
    """Invalid input is a 422 whose body never contains the submitted password."""
    admin = _make_user(db_session, UserRole.ADMIN)

    response = _client(db_session, app, admin).post("/users", json=body)

    assert response.status_code == 422
    # FastAPI's default body would echo the rejected value under "input".
    assert '"input"' not in response.text
    assert STRONG_PASSWORD not in response.text


def test_change_role_updates_and_audits_before_and_after(app: FastAPI, db_session: Session) -> None:
    """Promoting a rep to manager returns 200 and audits the old and new role."""
    admin = _make_user(db_session, UserRole.ADMIN)
    rep = _make_user(db_session, UserRole.REP, name="rep1")

    response = _client(db_session, app, admin).patch(f"/users/{rep.id}", json={"role": "manager"})

    assert response.status_code == 200
    assert response.json()["role"] == "manager"
    row = db_session.execute(
        select(AuditLog).where(AuditLog.action == AuditAction.USER_ROLE_CHANGED.value)
    ).scalar_one()
    assert row.summary == {"from": "rep", "to": "manager"}


def test_change_to_same_role_writes_no_audit(app: FastAPI, db_session: Session) -> None:
    """Setting the role a user already has is a 200 no-op with no audit row."""
    admin = _make_user(db_session, UserRole.ADMIN)
    rep = _make_user(db_session, UserRole.REP, name="rep1")

    response = _client(db_session, app, admin).patch(f"/users/{rep.id}", json={"role": "rep"})

    assert response.status_code == 200
    assert AuditAction.USER_ROLE_CHANGED.value not in _audit_actions(db_session)


def test_admin_cannot_demote_themselves(app: FastAPI, db_session: Session) -> None:
    """An admin changing their own role is refused with 409 and nothing changes."""
    admin = _make_user(db_session, UserRole.ADMIN)
    _make_user(db_session, UserRole.ADMIN, name="other-admin")

    response = _client(db_session, app, admin).patch(f"/users/{admin.id}", json={"role": "rep"})

    assert response.status_code == 409
    assert db_session.get(User, admin.id).role == UserRole.ADMIN


def test_admin_cannot_deactivate_themselves(app: FastAPI, db_session: Session) -> None:
    """An admin deactivating their own account is refused with 409."""
    admin = _make_user(db_session, UserRole.ADMIN)
    _make_user(db_session, UserRole.ADMIN, name="other-admin")

    response = _client(db_session, app, admin).post(f"/users/{admin.id}/deactivate")

    assert response.status_code == 409
    assert db_session.get(User, admin.id).is_active is True


def test_guard_refuses_to_remove_the_only_active_admin(db_session: Session) -> None:
    """Guard level: removing the only active admin raises LastAdminError.

    Not reachable through the API with a single caller (an active admin target other than
    the actor implies at least two admins), so the guard is called directly; it exists for
    the concurrent case where two admins remove each other at once.
    """
    only_admin = _make_user(db_session, UserRole.ADMIN, name="only")
    inactive_admin = _make_user(db_session, UserRole.ADMIN, name="inactive")
    inactive_admin.is_active = False  # not counted, so only_admin is the last active admin
    db_session.flush()

    with pytest.raises(user_services.LastAdminError):
        user_services._guard_admin_loss(db_session, inactive_admin, only_admin)


def test_deactivate_revokes_sessions_and_blocks_access(app: FastAPI, db_session: Session) -> None:
    """Deactivation: 200, the user's existing session stops working (401), and it is audited."""
    admin = _make_user(db_session, UserRole.ADMIN)
    rep = _make_user(db_session, UserRole.REP, name="rep1")
    rep_client = _client(db_session, app, rep)
    assert rep_client.get("/users/me").status_code == 200

    response = _client(db_session, app, admin).post(f"/users/{rep.id}/deactivate")

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert rep_client.get("/users/me").status_code == 401
    assert AuditAction.USER_DISABLED.value in _audit_actions(db_session)


def test_deactivate_is_idempotent(app: FastAPI, db_session: Session) -> None:
    """Deactivating an already inactive user is 200 and writes only one audit row."""
    admin = _make_user(db_session, UserRole.ADMIN)
    rep = _make_user(db_session, UserRole.REP, name="rep1")
    client = _client(db_session, app, admin)

    client.post(f"/users/{rep.id}/deactivate")
    second = client.post(f"/users/{rep.id}/deactivate")

    assert second.status_code == 200
    assert _audit_actions(db_session).count(AuditAction.USER_DISABLED.value) == 1


def test_reactivate_restores_access_only_with_a_new_session(
    app: FastAPI, db_session: Session
) -> None:
    """Reactivation: 200 and audited; the old session stays revoked, a new one works."""
    admin = _make_user(db_session, UserRole.ADMIN)
    rep = _make_user(db_session, UserRole.REP, name="rep1")
    old_client = _client(db_session, app, rep)
    admin_client = _client(db_session, app, admin)
    admin_client.post(f"/users/{rep.id}/deactivate")

    response = admin_client.post(f"/users/{rep.id}/reactivate")

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    assert old_client.get("/users/me").status_code == 401
    assert _client(db_session, app, rep).get("/users/me").status_code == 200
    assert AuditAction.USER_ENABLED.value in _audit_actions(db_session)


def test_unknown_user_is_404(app: FastAPI, db_session: Session) -> None:
    """Editing, deactivating or reactivating a missing id is 404 with a fixed body."""
    admin = _make_user(db_session, UserRole.ADMIN)
    client = _client(db_session, app, admin)
    missing = uuid.uuid4()

    for response in (
        client.patch(f"/users/{missing}", json={"role": "rep"}),
        client.post(f"/users/{missing}/deactivate"),
        client.post(f"/users/{missing}/reactivate"),
    ):
        assert response.status_code == 404
        assert response.json() == {"detail": "User not found"}


def test_openapi_documents_the_narrow_422_body() -> None:
    """OpenAPI points every 422 at ValidationErrorResponse (type, loc, msg only)."""
    schema = real_app.openapi()
    ref = schema["paths"]["/auth/login"]["post"]["responses"]["422"]["content"]["application/json"][
        "schema"
    ]

    assert ref == {"$ref": "#/components/schemas/ValidationErrorResponse"}
    assert "HTTPValidationError" not in schema["components"]["schemas"]
    item = schema["components"]["schemas"]["ValidationErrorItem"]
    assert set(item["properties"]) == {"type", "loc", "msg"}
