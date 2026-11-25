"""Smoke tests for the A-side test factories (core, leads, imports, compliance).

Needed so a factory can never drift away from models.py unnoticed: every factory must insert a
valid row on real PostgreSQL, repeated calls must not collide on a UNIQUE constraint, and
overrides must win. B11 and later milestones build their tests on these factories.
"""

from collections.abc import Callable

import pytest
from factories import compliance, core, imports, leads
from sqlalchemy.orm import Session

from app.compliance.models import ChecklistItemKey

Factory = Callable[[Session], object]

# Factories that insert a new row every call, so they can be called repeatedly in one test.
REPEATABLE_FACTORIES: list[Factory] = [
    core.make_user,
    core.make_user_session,
    core.make_setting,
    core.make_job_lock,
    leads.make_company,
    leads.make_person,
    leads.make_person_email,
    leads.make_person_phone,
    leads.make_social_profile,
    leads.make_contact_channel,
    leads.make_quarantine_record,
    leads.make_duplicate_candidate,
    leads.make_merge_record,
    leads.make_segment,
    leads.make_lead_note,
    leads.make_lead_event,
    leads.make_touch,
    leads.make_lead_status_flag,
    leads.make_industry_mapping,
    leads.make_state_mapping,
    imports.make_source_profile,
    imports.make_import_file,
    imports.make_column_mapping,
    imports.make_raw_row,
    imports.make_import_report,
    imports.make_import_change,
    compliance.make_opt_out,
    compliance.make_erasure_record,
]

# Single-row tables: the clock offset allows one row; the gate status and checklist rows are
# seeded by migration 0008, so their factories return the existing row.
SINGLE_ROW_FACTORIES: list[Factory] = [
    core.make_clock_offset,
    compliance.make_compliance_gate_status,
    compliance.make_compliance_checklist_item,
]


@pytest.mark.parametrize("factory", REPEATABLE_FACTORIES, ids=lambda f: f.__name__)
def test_factory_inserts_distinct_valid_rows(db_session: Session, factory: Factory) -> None:
    """Calling a factory twice inserts two valid rows with different ids and no constraint error."""
    first = factory(db_session)
    second = factory(db_session)
    assert first.id is not None  # type: ignore[attr-defined]
    assert first.id != second.id  # type: ignore[attr-defined]


@pytest.mark.parametrize("factory", SINGLE_ROW_FACTORIES, ids=lambda f: f.__name__)
def test_single_row_factory_returns_a_valid_row(db_session: Session, factory: Factory) -> None:
    """A single-row factory returns one row with an id (new, or the one the migration seeded)."""
    assert factory(db_session).id is not None  # type: ignore[attr-defined]


def test_overrides_replace_defaults(db_session: Session) -> None:
    """An override wins over the factory default."""
    assert leads.make_person(db_session, first_name="Zed").first_name == "Zed"


def test_seeded_factories_return_the_migration_rows(db_session: Session) -> None:
    """The gate factory returns the seeded disabled row and the checklist factory the right key."""
    assert compliance.make_compliance_gate_status(db_session).real_sending_enabled is False
    item = compliance.make_compliance_checklist_item(db_session, ChecklistItemKey.FOOTER_SAVED)
    assert item.item_key == ChecklistItemKey.FOOTER_SAVED
