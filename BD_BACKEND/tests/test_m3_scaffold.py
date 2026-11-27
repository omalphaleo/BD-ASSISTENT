"""Tests for the M3-0 scaffold: empty routers, audit actions and the three new permissions.

Needed so the names both M3 workstreams build on (the pre-mounted routers, the AuditAction
vocabulary and the new capabilities) cannot drift or be removed unnoticed. No database is
used: everything here is plain Python.
"""

import pytest
from fastapi import APIRouter

import app.main as main_module
from app.audit.services import AuditAction
from app.compliance import opt_outs_api
from app.core.models import UserRole
from app.core.permissions import PERMISSION_ROLES, Permission
from app.leads import companies_api, people_api, search_api, segments_api

M3_AUDIT_ACTIONS = {
    "OPT_OUT_ADDED": "opt_out.added",
    "OPT_OUT_REMOVED": "opt_out.removed",
    "PERSON_ERASED": "person.erased",
    "LEAD_OWNER_ASSIGNED": "lead.owner_assigned",
    "LEAD_FLAG_SET": "lead.flag_set",
    "LEAD_FLAG_CLEARED": "lead.flag_cleared",
    "LEAD_NOTE_ADDED": "lead.note_added",
    "SEGMENT_CREATED": "segment.created",
    "SEGMENT_UPDATED": "segment.updated",
    "SEGMENT_DELETED": "segment.deleted",
    "EXPORT_LEADS_DOWNLOADED": "export.leads_downloaded",
    "SEARCH_NL_INTERPRETED": "search.nl_interpreted",
}

# (router module, expected prefix, expected tag, name main.py imports it under)
ROUTERS = [
    (search_api, "/search", "search", "search_router"),
    (segments_api, "/segments", "segments", "segments_router"),
    (people_api, "/people", "people", "people_router"),
    (companies_api, "/companies", "companies", "companies_router"),
    (opt_outs_api, "/opt-outs", "opt-outs", "opt_outs_router"),
]


# Routers whose endpoints are built; a router leaves the "still empty" check when its task lands
# (search_api: M3-A2, segments_api: M3-A4).
ROUTERS_WITH_ENDPOINTS = {search_api, segments_api}


@pytest.mark.parametrize(("module", "prefix", "tag", "main_name"), ROUTERS)
def test_m3_router_is_empty_prefixed_and_mounted(
    module: object, prefix: str, tag: str, main_name: str
) -> None:
    """Each M3 router has its prefix and tag, is imported by main.py, and is empty until built."""
    router = module.router  # type: ignore[attr-defined]
    assert isinstance(router, APIRouter)
    assert router.prefix == prefix
    assert router.tags == [tag]
    if module not in ROUTERS_WITH_ENDPOINTS:
        assert router.routes == []
    assert getattr(main_module, main_name) is router


def test_m3_audit_actions_exist_with_agreed_values() -> None:
    """All 12 M3 audit actions exist with area.event values, and no value is duplicated."""
    for member, value in M3_AUDIT_ACTIONS.items():
        assert AuditAction[member].value == value
    values = [action.value for action in AuditAction]
    assert len(values) == len(set(values))


@pytest.mark.parametrize(
    "permission", [Permission.ADD_OPT_OUT, Permission.VIEW_OPT_OUTS, Permission.ADD_NOTE]
)
def test_new_m3_permissions_are_granted_to_every_role(permission: Permission) -> None:
    """ADD_OPT_OUT (D-066), VIEW_OPT_OUTS (D-067) and ADD_NOTE are open to rep, manager, admin."""
    assert PERMISSION_ROLES[permission] == frozenset(UserRole)
