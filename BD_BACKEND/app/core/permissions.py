"""Central permission module: the capability table, route guards and the owner-only check.

Needed so access is enforced on the server in one reviewable place (plan.md section 4, never
only by hiding buttons). Every route declares exactly one guard, `public_route` or
`require_permission(...)`; the role-by-endpoint matrix test reads those declarations and
fails on any route without one. Services call `require_owner` to re-check object ownership.
"""

import enum
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import FastAPI
from fastapi import routing as fastapi_routing
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.core.dependencies import NOT_AUTHENTICATED_DETAIL, CurrentUser
from app.core.models import User, UserRole
from app.core.schemas import ErrorResponse

# One fixed body for every denial, so a 403 never reveals the capability, the owner or any
# lead data (decision A6-5).
PERMISSION_DENIED_DETAIL = "Not permitted"

ERROR_RESPONSE_SCHEMA_NAME = "ErrorResponse"
_SCHEMA_REF = f"#/components/schemas/{ERROR_RESPONSE_SCHEMA_NAME}"


class Permission(enum.StrEnum):
    """One capability per row of the plan.md section 4 table (granularity noted per member).

    "Log in / out" has no member: those routes are `public_route`. Members whose row also
    has an object-level rule ("importer only", "within own visibility") grant only the role
    part here; the milestone that builds the endpoint adds the object check.
    """

    # Own profile (used by /auth/me and, in A7, "my profile").
    VIEW_OWN_PROFILE = "view_own_profile"
    # Leads and import (planned: M2, M3).
    IMPORT_LEADS = "import_leads"
    VIEW_OWN_LEADS = "view_own_leads"
    VIEW_ALL_LEADS = "view_all_leads"
    ASSIGN_LEADS = "assign_leads"
    FIX_QUARANTINE = "fix_quarantine"
    DISCARD_QUARANTINE = "discard_quarantine"  # rep: importer only (object-level, planned)
    SET_LEAD_STATUS_FLAG = "set_lead_status_flag"
    MANAGE_SOURCE_PROFILES = "manage_source_profiles"  # also industry / state mappings
    REVIEW_DUPLICATES = "review_duplicates"
    EXPORT_CSV = "export_csv"  # within the caller's own visibility (object-level, planned)
    DOWNLOAD_IMPORT_FILES = "download_import_files"  # rep: importer only (object-level)
    CREATE_SEGMENT = "create_segment"  # private/shared rules are object-level (planned)
    # Campaigns and drafts (planned: M4). Only reps author and approve outreach (Q-ROLES-03).
    EDIT_DRAFT = "edit_draft"
    APPROVE_DRAFT = "approve_draft"
    VIEW_ALL_DRAFTS = "view_all_drafts"
    # Compliance (planned: M3, M8).
    REMOVE_OPT_OUT = "remove_opt_out"
    ERASE_PERSON = "erase_person"
    ACTIVATE_REAL_SENDING = "activate_real_sending"
    # Content and administration (planned: M5). The "sending limits, mailboxes, users, test
    # clock" row is split so each admin endpoint names what it guards.
    VIEW_CONTENT_CONFIG = "view_content_config"
    EDIT_CONTENT_CONFIG = "edit_content_config"  # voice, profiles, KB, structures
    MANAGE_USERS = "manage_users"
    MANAGE_SENDING_LIMITS = "manage_sending_limits"
    MANAGE_MAILBOXES = "manage_mailboxes"
    MANAGE_TEST_CLOCK = "manage_test_clock"


_ALL_ROLES = frozenset(UserRole)
_MANAGER_UP = frozenset({UserRole.MANAGER, UserRole.ADMIN})
_ADMIN_ONLY = frozenset({UserRole.ADMIN})
_REP_ONLY = frozenset({UserRole.REP})

# The single source of truth for who may use each capability (plan.md section 4, [AGREED]).
PERMISSION_ROLES: dict[Permission, frozenset[UserRole]] = {
    Permission.VIEW_OWN_PROFILE: _ALL_ROLES,
    Permission.IMPORT_LEADS: _ALL_ROLES,  # D-104
    Permission.VIEW_OWN_LEADS: _ALL_ROLES,
    Permission.VIEW_ALL_LEADS: _ALL_ROLES,  # D-001, D-026
    Permission.ASSIGN_LEADS: _MANAGER_UP,  # D-075
    Permission.FIX_QUARANTINE: _ALL_ROLES,
    Permission.DISCARD_QUARANTINE: _ALL_ROLES,
    Permission.SET_LEAD_STATUS_FLAG: _ALL_ROLES,  # D-101
    Permission.MANAGE_SOURCE_PROFILES: _ADMIN_ONLY,  # D-104
    Permission.REVIEW_DUPLICATES: _MANAGER_UP,
    Permission.EXPORT_CSV: _ALL_ROLES,  # D-087
    Permission.DOWNLOAD_IMPORT_FILES: _ALL_ROLES,  # D-111
    Permission.CREATE_SEGMENT: _ALL_ROLES,  # D-098
    Permission.EDIT_DRAFT: _REP_ONLY,  # owner only; managers and admins are read-only
    Permission.APPROVE_DRAFT: _REP_ONLY,  # owner only
    Permission.VIEW_ALL_DRAFTS: _MANAGER_UP,  # read-only
    Permission.REMOVE_OPT_OUT: _MANAGER_UP,
    Permission.ERASE_PERSON: _ADMIN_ONLY,  # D-099
    Permission.ACTIVATE_REAL_SENDING: _ADMIN_ONLY,  # compliance gate
    Permission.VIEW_CONTENT_CONFIG: _ALL_ROLES,
    Permission.EDIT_CONTENT_CONFIG: _ADMIN_ONLY,
    Permission.MANAGE_USERS: _ADMIN_ONLY,
    Permission.MANAGE_SENDING_LIMITS: _ADMIN_ONLY,
    Permission.MANAGE_MAILBOXES: _ADMIN_ONLY,
    Permission.MANAGE_TEST_CLOCK: _ADMIN_ONLY,
}


class PermissionDeniedError(Exception):
    """Raised when a signed-in user lacks a capability or does not own an object.

    app.core.errors turns it into a 403 with the fixed PERMISSION_DENIED_DETAIL body.
    """


def has_permission(user: User, permission: Permission) -> bool:
    """Tell whether the user's role grants the capability.

    A deactivated user never has a permission, as a second line of defence behind the 401
    that current_user already gives them.
    """
    return user.is_active and user.role in PERMISSION_ROLES[permission]


def is_owner(user: User, owner_id: uuid.UUID | None) -> bool:
    """Tell whether the user owns an object whose owner id is `owner_id`.

    Args:
        user: The signed-in user.
        owner_id: The object's owner, or None when it has none (such an object is nobody's).
    """
    return owner_id is not None and user.id == owner_id


def require_owner(user: User, owner_id: uuid.UUID | None) -> None:
    """Owner-only rule for services: only the object's owner may pass.

    Called in addition to the role capability (for example EDIT_DRAFT) so a background job
    or a second route cannot skip the ownership check (plan.md section 4).

    Raises:
        PermissionDeniedError: If the user is not the owner.
    """
    if not is_owner(user, owner_id):
        raise PermissionDeniedError


class PermissionGuard:
    """Route dependency that demands one capability; carries it so tests can read it back."""

    def __init__(self, permission: Permission) -> None:
        self.permission = permission

    def __call__(self, current_user: CurrentUser) -> User:
        """Return the signed-in user if their role grants the capability.

        Raises:
            HTTPException: 401 via current_user when nobody is signed in (checked first).
            PermissionDeniedError: If the role lacks the capability (rendered as 403).
        """
        if not has_permission(current_user, self.permission):
            raise PermissionDeniedError
        return current_user


class PublicRoute:
    """No-op marker dependency: states that a route is public on purpose."""

    def __call__(self) -> None:
        """Do nothing; the marker only exists for the matrix test to find."""


def require_permission(permission: Permission) -> PermissionGuard:
    """Build the dependency for a route that needs `permission` (used as Depends(...))."""
    return PermissionGuard(permission)


# Declared on routes anyone may call, e.g. dependencies=[Depends(public_route)].
public_route = PublicRoute()


@dataclass(frozen=True)
class RouteDeclaration:
    """What a route declares: public on purpose, and/or the capabilities it requires."""

    public: bool
    permissions: tuple[Permission, ...]

    @property
    def is_valid(self) -> bool:
        """A route must declare exactly one way: public, or at least one capability."""
        return self.public != bool(self.permissions)


def _dependency_calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    """Yield every dependency callable reachable from a route, including nested ones."""
    for sub in dependant.dependencies:
        if sub.call is not None:
            yield sub.call
        yield from _dependency_calls(sub)


class ApiRouteView(Protocol):
    """The route attributes this module reads (an APIRoute or a FastAPI RouteContext has them)."""

    @property
    def path_format(self) -> str | None:
        """The route's path template, e.g. /auth/me (includes any router prefix)."""

    @property
    def methods(self) -> set[str] | None:
        """The HTTP methods the route answers."""

    @property
    def dependant(self) -> Dependant:
        """The route's dependency tree, including router-level dependencies."""


def get_route_declaration(route: ApiRouteView) -> RouteDeclaration:
    """Read what the route declares by inspecting its actual dependencies.

    Reading the enforcing dependency itself means the declaration cannot drift from what
    is enforced (decision A6-3).
    """
    calls = list(_dependency_calls(route.dependant))
    return RouteDeclaration(
        public=any(isinstance(call, PublicRoute) for call in calls),
        permissions=tuple(call.permission for call in calls if isinstance(call, PermissionGuard)),
    )


def iter_api_routes(app: FastAPI) -> Iterator[ApiRouteView]:
    """Yield every API route of the app, with prefixes and router-level dependencies applied.

    FastAPI's own /docs and /openapi.json are not API routes and are skipped. Newer FastAPI
    keeps included routers lazy (app.routes holds an opaque wrapper), so the public
    iter_route_contexts is used when it exists; older FastAPI copies routes flat into
    app.routes. The canary test fails if a FastAPI upgrade stops either path working.
    """
    iter_route_contexts = getattr(fastapi_routing, "iter_route_contexts", None)
    if iter_route_contexts is None:
        yield from (route for route in app.routes if isinstance(route, APIRoute))
        return
    for context in iter_route_contexts(app.routes):
        if isinstance(context.original_route, APIRoute):
            yield context


def _error_response(description: str) -> dict[str, Any]:
    """Build an OpenAPI response entry that points at the shared ErrorResponse schema."""
    return {
        "description": description,
        "content": {"application/json": {"schema": {"$ref": _SCHEMA_REF}}},
    }


def install_permission_openapi(app: FastAPI) -> None:
    """Document 401 and 403 on every permission-guarded route in the OpenAPI schema.

    Done once from the same declarations the matrix test reads, so the schema cannot drift
    from enforcement and routes need no per-route `responses=` (decision A6-8).
    """
    build_default_schema = app.openapi

    def openapi_with_permission_errors() -> dict[str, Any]:
        schema = build_default_schema()
        schemas = schema.setdefault("components", {}).setdefault("schemas", {})
        if ERROR_RESPONSE_SCHEMA_NAME in schemas:  # already added; FastAPI caches the schema
            return schema
        schemas[ERROR_RESPONSE_SCHEMA_NAME] = ErrorResponse.model_json_schema()
        for route in iter_api_routes(app):
            if not get_route_declaration(route).permissions:
                continue
            if route.path_format not in schema["paths"]:  # include_in_schema=False
                continue
            for method in route.methods or ():
                responses = schema["paths"][route.path_format][method.lower()]["responses"]
                responses["401"] = _error_response(NOT_AUTHENTICATED_DETAIL)
                responses["403"] = _error_response(PERMISSION_DENIED_DETAIL)
        return schema

    app.openapi = openapi_with_permission_errors  # type: ignore[method-assign]
