"""Define the application's central server-side permission rules.

This module translates the role rules in plan.md section 4 into named capabilities,
FastAPI route guards, and an owner-only check. It is used whenever an endpoint or
service must decide whether a signed-in user is allowed to perform an action.

Every route should declare either that it is public or which capability it requires.
The route tests read those declarations and compare them with the permission table,
preventing a route from being left unprotected accidentally.
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
    """Name an action that the application is allowed to authorize.

    Each member represents one capability from plan.md section 4. Routes use these
    names with `require_permission()` so the role they need is visible at the
    endpoint. Login and logout do not have a member because they are public routes.

    Some capabilities also need object-specific rules later, such as importing
    only files owned by the caller or exporting leads within the caller's
    visibility. This enum grants the role portion; `require_owner()` or another
    service-level check adds that finer rule.
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
    """Report that an authenticated action was denied.

    The exception is raised by route guards and service-level owner checks when
    the user has a valid session but is not allowed to continue. It carries no
    user-facing details.

    The API error handler in `app.core.errors` converts this exception into the
    fixed 403 response body defined by `PERMISSION_DENIED_DETAIL`.
    """


def has_permission(user: User, permission: Permission) -> bool:
    """Check whether a user may use a capability.

    This is the role lookup used by permission guards and service code. The user
    must be active, and their role must appear in `PERMISSION_ROLES[permission]`.

    Args:
        user: The authenticated user to check.
        permission: The capability required by the route or service.

    Returns:
        `True` if the user is active and their role grants the capability;
        otherwise `False`.

    Example:
        An admin is allowed `MANAGE_USERS`, while an inactive admin is not.
    """
    return user.is_active and user.role in PERMISSION_ROLES[permission]


def is_owner(user: User, owner_id: uuid.UUID | None) -> bool:
    """Check whether a user owns an object.

    This helper supports object-level rules that cannot be decided by role
    alone. For example, a rep may edit drafts generally but only their own.

    Args:
        user: The authenticated user.
        owner_id: The object's owner ID, or `None` if the object has no owner.

    Returns:
        `True` only when `owner_id` is present and matches the user's ID.
    """
    return owner_id is not None and user.id == owner_id


def require_owner(user: User, owner_id: uuid.UUID | None) -> None:
    """Require a user to own the object being changed.

    Services call this after or alongside a role capability. It prevents another
    route or background task from bypassing an ownership rule. For example,
    `EDIT_DRAFT` also requires ownership of the specific draft.

    Args:
        user: The authenticated user making the request.
        owner_id: The object's owner ID, or `None` if it has no owner.

    Raises:
        PermissionDeniedError: If the object has no owner or belongs to someone
            else, for every user role.
    """
    if not is_owner(user, owner_id):
        raise PermissionDeniedError


class PermissionGuard:
    """Protect a FastAPI route with one named capability.

    A route creates a guard through `require_permission()`. FastAPI calls the
    guard after resolving the current authenticated user, then checks whether
    that user is active and has the required role.

    The guard stores its capability so route matrix tests can inspect the real
    dependency attached to an endpoint.
    """

    def __init__(self, permission: Permission) -> None:
        """Create a guard for one capability.

        Args:
            permission: The capability a caller must have to use the route.
        """
        self.permission = permission

    def __call__(self, current_user: CurrentUser) -> User:
        """Return the user only when their role grants the capability.

        Args:
            current_user: The authenticated user resolved from the session cookie.

        Returns:
            The authenticated user. Route handlers can use this object directly.

        Raises:
            HTTPException: Raised with 401 by `get_current_user()` if there is no
                valid signed-in session.
            PermissionDeniedError: Raised with 403 if the user is signed in but
                does not have this capability.
        """
        if not has_permission(current_user, self.permission):
            raise PermissionDeniedError
        return current_user


class PublicRoute:
    """Mark a route as intentionally public.

    This dependency performs no authorization work. It makes a public route
    visible to FastAPI and to the route matrix test. Examples include health
    checks, login, and logout.
    """

    def __call__(self) -> None:
        """Accept the request without checking a session or capability.

        This method intentionally does nothing. The dependency object remains
        attached to the route so tests can confirm the route was declared public.
        """


def require_permission(permission: Permission) -> PermissionGuard:
    """Create a FastAPI dependency for a required capability.

    Route handlers normally use this through `Depends(...)`. For example,
    `Depends(require_permission(Permission.MANAGE_USERS))` allows only an admin
    to call a user-management endpoint.

    Args:
        permission: The capability that a caller must have.

    Returns:
        A `PermissionGuard` configured for that capability.
    """
    return PermissionGuard(permission)


# Shared public-route marker used by routes anyone may call.
public_route = PublicRoute()


@dataclass(frozen=True)
class RouteDeclaration:
    """Describe a route's public or permission declaration.

    The route matrix test uses this value to ensure that every endpoint chooses
    exactly one access model: it is public or it requires one or more
    capabilities.
    """

    public: bool
    permissions: tuple[Permission, ...]

    @property
    def is_valid(self) -> bool:
        """Check whether the route has exactly one valid access declaration.

        Returns:
            `True` for a public route with no permissions or a protected route
            with at least one permission. `False` for a route with neither
            declaration or both kinds of declaration.
        """
        return self.public != bool(self.permissions)


def _dependency_calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    """Find dependency functions used by a route and its nested dependencies.

    FastAPI may attach dependencies directly to a route or through included
    routers. This helper recursively walks that dependency tree and yields each
    callable. `get_route_declaration()` uses the results to locate public-route
    and permission guard objects.

    Args:
        dependant: The FastAPI dependency tree to inspect.

    Returns:
        An iterator of dependency callables, including nested callables.
    """
    for sub in dependant.dependencies:
        if sub.call is not None:
            yield sub.call
        yield from _dependency_calls(sub)


class ApiRouteView(Protocol):
    """Describe the route attributes needed for authorization inspection.

    FastAPI exposes a route or route context depending on the framework version.
    This protocol gives both forms the small shared interface used here: path,
    HTTP methods, and dependency tree.
    """

    @property
    def path_format(self) -> str | None:
        """Return the route template, such as `/users/{user_id}`."""

    @property
    def methods(self) -> set[str] | None:
        """Return the HTTP methods handled by the route."""

    @property
    def dependant(self) -> Dependant:
        """Return the route's complete dependency tree."""


def get_route_declaration(route: ApiRouteView) -> RouteDeclaration:
    """Read a route's public or permission declaration from its dependencies.

    This function inspects the actual guard objects attached to the route rather
    than a separate metadata table. That keeps tests tied to the authorization
    behavior FastAPI will enforce.

    Args:
        route: An API route or route context to inspect.

    Returns:
        A `RouteDeclaration` stating whether the route is public and listing all
        permission guards found in its dependency tree.
    """
    calls = list(_dependency_calls(route.dependant))
    return RouteDeclaration(
        public=any(isinstance(call, PublicRoute) for call in calls),
        permissions=tuple(call.permission for call in calls if isinstance(call, PermissionGuard)),
    )


def iter_api_routes(app: FastAPI) -> Iterator[ApiRouteView]:
    """Yield application API routes in a FastAPI-version-safe way.

    Framework routes such as `/docs` and `/openapi.json` are skipped. Newer
    FastAPI versions expose routers through route contexts, while older versions
    place `APIRoute` objects directly in `app.routes`. This function detects
    both layouts so route authorization tests continue to work across upgrades.

    Args:
        app: The FastAPI application whose API routes should be inspected.

    Returns:
        An iterator of route objects containing path, method, and dependency
        information.
    """
    iter_route_contexts = getattr(fastapi_routing, "iter_route_contexts", None)
    if iter_route_contexts is None:
        yield from (route for route in app.routes if isinstance(route, APIRoute))
        return
    for context in iter_route_contexts(app.routes):
        if isinstance(context.original_route, APIRoute):
            yield context


def _error_response(description: str) -> dict[str, Any]:
    """Build an OpenAPI response entry for a standardized error.

    Args:
        description: Human-readable explanation of the response status.

    Returns:
        A dictionary containing the description and a JSON reference to
        `ErrorResponse` in the OpenAPI components section.
    """
    return {
        "description": description,
        "content": {"application/json": {"schema": {"$ref": _SCHEMA_REF}}},
    }


def install_permission_openapi(app: FastAPI) -> None:
    """Add authentication and authorization responses to guarded routes.

    This function wraps the application's OpenAPI generator. Whenever the
    schema is requested, it inspects each route and adds `401` and `403`
    responses to routes that require permissions. Public routes are unchanged.

    The `401` response describes an invalid or missing session. The `403`
    response describes a valid session that lacks permission. Both responses use
    the shared `ErrorResponse` schema, so routes do not need separate
    `responses=` declarations.

    Args:
        app: The FastAPI application to update.

    Returns:
        Nothing. The function replaces `app.openapi` with a schema wrapper.
    """
    build_default_schema = app.openapi

    def openapi_with_permission_errors() -> dict[str, Any]:
        """Build the normal schema and add permission error responses."""
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
