"""Unit tests for core.permissions: the capability table, the owner-only rule and the 403 body.

Needed because these functions decide who may do what: the table must cover every capability,
the owner check must treat "no owner" as nobody's, and a denial must return one fixed body.
No database is used; users are built in memory and the 403 test drives a tiny app.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import register_error_handlers
from app.core.models import User, UserRole
from app.core.permissions import (
    PERMISSION_DENIED_DETAIL,
    PERMISSION_ROLES,
    Permission,
    PermissionDeniedError,
    has_permission,
    is_owner,
    require_owner,
)


def _user(role: UserRole = UserRole.REP, *, is_active: bool = True) -> User:
    """Build an unsaved synthetic user; no database is involved."""
    return User(
        id=uuid.uuid4(),
        email=f"{role.value}@example.com",
        password_hash="not-a-real-hash",
        role=role,
        is_active=is_active,
    )


def test_every_permission_has_a_non_empty_role_set() -> None:
    """The table covers every Permission member and each grants at least one role."""
    assert set(PERMISSION_ROLES) == set(Permission)
    assert all(PERMISSION_ROLES[permission] for permission in Permission)


@pytest.mark.parametrize("role", list(UserRole))
def test_has_permission_follows_the_table(role: UserRole) -> None:
    """has_permission is True exactly for the roles the table grants, for every capability."""
    user = _user(role)
    for permission in Permission:
        assert has_permission(user, permission) is (role in PERMISSION_ROLES[permission])


def test_inactive_user_has_no_permission() -> None:
    """A deactivated admin is denied even a capability the admin role grants."""
    assert has_permission(_user(UserRole.ADMIN, is_active=False), Permission.MANAGE_USERS) is False


def test_only_reps_may_edit_or_approve_drafts_others_read_only() -> None:
    """Q-ROLES-03: managers and admins can view all drafts but never edit or approve them."""
    for role in (UserRole.MANAGER, UserRole.ADMIN):
        user = _user(role)
        assert has_permission(user, Permission.VIEW_ALL_DRAFTS)
        assert not has_permission(user, Permission.EDIT_DRAFT)
        assert not has_permission(user, Permission.APPROVE_DRAFT)
    rep = _user(UserRole.REP)
    assert has_permission(rep, Permission.EDIT_DRAFT)
    assert has_permission(rep, Permission.APPROVE_DRAFT)
    assert not has_permission(rep, Permission.VIEW_ALL_DRAFTS)


def test_is_owner_true_only_for_the_matching_id() -> None:
    """The owner passes; another user and an object with no owner do not."""
    owner = _user()
    assert is_owner(owner, owner.id) is True
    assert is_owner(_user(), owner.id) is False
    assert is_owner(owner, None) is False


def test_require_owner_passes_for_the_owner() -> None:
    """The owner gets no exception."""
    owner = _user()
    require_owner(owner, owner.id)


@pytest.mark.parametrize("role", list(UserRole))
def test_require_owner_rejects_non_owners_of_every_role(role: UserRole) -> None:
    """Even a manager or admin is not the owner of someone else's object: PermissionDeniedError."""
    with pytest.raises(PermissionDeniedError):
        require_owner(_user(role), uuid.uuid4())


def test_permission_denied_error_becomes_the_fixed_403_body() -> None:
    """A denial raised inside a route returns exactly {"detail": "Not permitted"} with 403."""
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/denied")
    def denied() -> None:
        """Stand-in for a service that rejects a non-owner."""
        raise PermissionDeniedError("secret detail that must not reach the client")

    response = TestClient(app).get("/denied")

    assert response.status_code == 403
    assert response.json() == {"detail": PERMISSION_DENIED_DETAIL}
    assert "secret" not in response.text
