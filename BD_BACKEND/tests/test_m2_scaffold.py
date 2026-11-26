"""Tests for the M2-0 scaffold: contract types, wiring stub, empty routers, audit actions, worker.

Needed so the parts both M2 workstreams build on (leads/contracts.py, imports/wiring.py, the
pre-mounted routers, the AuditAction vocabulary and the worker task path) cannot drift or be
removed unnoticed. No database is used: everything here is plain Python.
"""

import uuid
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from fastapi import APIRouter

import app.main as main_module
from app.audit.services import AuditAction
from app.imports import api as imports_api
from app.imports import profiles_api
from app.imports.wiring import get_ingest_row
from app.leads import duplicates_api, mappings_api, quarantine_api
from app.leads.contracts import (
    FieldChange,
    ImportContext,
    IngestSource,
    RowOutcome,
    RowOutcomeKind,
    SourceRow,
)
from app.worker import app as worker_app

M2_AUDIT_ACTIONS = {
    "IMPORT_FILE_UPLOADED": "import.file_uploaded",
    "IMPORT_DUPLICATE_FILE_OVERRIDDEN": "import.duplicate_file_overridden",
    "IMPORT_MAPPING_CHANGED": "import.mapping_changed",
    "IMPORT_STARTED": "import.started",
    "IMPORT_FINISHED": "import.finished",
    "IMPORT_FAILED": "import.failed",
    "IMPORT_OWNER_ASSIGNED": "import.owner_assigned",
    "IMPORT_REPORT_DOWNLOADED": "import.report_downloaded",
    "SOURCE_PROFILE_CREATED": "source_profile.created",
    "SOURCE_PROFILE_UPDATED": "source_profile.updated",
    "QUARANTINE_FIXED": "quarantine.fixed",
    "QUARANTINE_RELEASED": "quarantine.released",
    "QUARANTINE_DISCARDED": "quarantine.discarded",
    "DUPLICATE_MERGED": "duplicate.merged",
    "DUPLICATE_MARKED_DISTINCT": "duplicate.marked_distinct",
    "REFERENCE_MAPPING_CHANGED": "mapping.reference_changed",
}

# (router module, expected prefix, expected tag, name main.py imports it under)
ROUTERS = [
    (imports_api, "/imports", "imports", "imports_router"),
    (profiles_api, "/source-profiles", "source-profiles", "source_profiles_router"),
    (quarantine_api, "/quarantine", "quarantine", "quarantine_router"),
    (duplicates_api, "/duplicates", "duplicates", "duplicates_router"),
    (mappings_api, "/reference-mappings", "reference-mappings", "reference_mappings_router"),
]


def test_row_outcome_kinds_match_the_import_report_counters() -> None:
    """RowOutcomeKind has exactly the six outcomes of m2.md section 18, as lowercase text."""
    assert {kind.value for kind in RowOutcomeKind} == {
        "imported",
        "updated",
        "unchanged",
        "quarantined",
        "possible_duplicate",
        "rejected",
    }


def test_contract_objects_are_immutable() -> None:
    """A SourceRow cannot be changed after W1 builds it, so W2 cannot alter W1's data."""
    row = SourceRow(
        row_number=1,
        values={"first_name": "Ada"},
        raw_email="Ada@Example.com",
        import_file_id=uuid.uuid4(),
        source_profile_id=None,
        default_country=None,
    )
    with pytest.raises(FrozenInstanceError):
        row.row_number = 2  # type: ignore[misc]


def test_row_outcome_defaults_have_no_reason_or_person() -> None:
    """A bare RowOutcome carries only its kind; reason and person are optional."""
    outcome = RowOutcome(kind=RowOutcomeKind.UNCHANGED)
    assert outcome.reason_code is None
    assert outcome.person_id is None


def test_import_context_carries_the_entry_point() -> None:
    """ImportContext records whether a call is an import or a quarantine release."""
    ctx = ImportContext(
        import_file_id=uuid.uuid4(),
        uploaded_by=None,
        now=datetime(2026, 11, 25, tzinfo=UTC),
        cooling_off_days=90,
        source=IngestSource.QUARANTINE_RELEASE,
    )
    assert ctx.source is IngestSource.QUARANTINE_RELEASE


def test_field_change_has_the_agreed_json_keys() -> None:
    """FieldChange is the {field, old, new} item stored in ImportChange.changes."""
    assert set(FieldChange.__dataclass_fields__) == {"field", "old", "new"}


def test_unwired_ingest_row_fails_loudly() -> None:
    """Before integration step I1 the stub raises instead of reporting fake successes."""
    ingest_row = get_ingest_row()
    row = SourceRow(1, {}, None, uuid.uuid4(), None, None)
    ctx = ImportContext(
        uuid.uuid4(), None, datetime(2026, 11, 25, tzinfo=UTC), 90, IngestSource.IMPORT
    )
    with pytest.raises(NotImplementedError):
        ingest_row(None, row, ctx)  # type: ignore[arg-type]


@pytest.mark.parametrize(("module", "prefix", "tag", "main_name"), ROUTERS)
def test_m2_router_is_empty_prefixed_and_mounted(
    module: object, prefix: str, tag: str, main_name: str
) -> None:
    """Each M2 router has its prefix and tag and is imported by main.py; unbuilt ones are empty."""
    router = module.router  # type: ignore[attr-defined]
    assert isinstance(router, APIRouter)
    assert router.prefix == prefix
    assert router.tags == [tag]
    # M2-A1 gave /imports its first routes; M2-B2 gave /quarantine its own.
    if module not in (imports_api, quarantine_api, duplicates_api, mappings_api):
        assert router.routes == []
    assert getattr(main_module, main_name) is router


def test_m2_audit_actions_exist_with_agreed_values() -> None:
    """All 16 M2 audit actions exist with area.event values, and no value is duplicated."""
    for member, value in M2_AUDIT_ACTIONS.items():
        assert AuditAction[member].value == value
    values = [action.value for action in AuditAction]
    assert len(values) == len(set(values))


def test_worker_loads_the_imports_task_module() -> None:
    """The worker lists app.imports.tasks, so M2-A3 can add its task without editing worker.py."""
    assert "app.imports.tasks" in worker_app.import_paths
