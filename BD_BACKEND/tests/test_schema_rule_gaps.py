"""Schema rule gap tests for A's tables: foreign keys that point nowhere and unchecked CHECKs.

Needed because the A2-A5 model tests prove delete rules and uniqueness but not that every
foreign key rejects a missing parent, nor three non-negative CHECKs and four fixed-value
CHECKs. Each case builds a valid row with a factory, then makes one column invalid and expects
PostgreSQL to refuse it by constraint name. Uses real PostgreSQL; all data is synthetic.
"""

# The case tables below put one case per line so each reads as a row; a few lines are long.
# ruff: noqa: E501

import uuid
from collections.abc import Callable

import pytest
from factories import compliance, imports, leads
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.compliance.models import (
    ComplianceChecklistItem,
    ComplianceGateStatus,
    ErasureRecord,
    OptOut,
)
from app.core.clock import now
from app.imports.models import (
    ColumnMapping,
    ImportChange,
    ImportFile,
    ImportReport,
    RawRow,
    SourceProfile,
)
from app.leads.models import (
    ContactChannel,
    DuplicateCandidate,
    LeadEvent,
    LeadNote,
    LeadStatusFlag,
    MergeRecord,
    Person,
    PersonEmail,
    PersonPhone,
    QuarantineRecord,
    Segment,
    SocialProfile,
    Touch,
)

# Short names keep the case table readable.
cmp = compliance
imp = imports
lds = leads

# Pair ordering is a CHECK too (person_a_id < person_b_id), so these two values keep the
# ordering valid and let the foreign key be the only rule that fails.
LOWEST_UUID = uuid.UUID(int=1)
HIGHEST_UUID = uuid.UUID(int=2**128 - 1)

# removed_by may only be set together with removed_at and removal_reason (a CHECK).
OPT_OUT_REMOVED = {"removed_at": now(), "removal_reason": "Synthetic."}

# (model, column, factory, constraint). Each column is set to an id that does not exist.
FOREIGN_KEY_CASES = [
    (ColumnMapping, "import_file_id", imp.make_column_mapping, "fk_column_mappings_import_file_id_files"),
    (ComplianceChecklistItem, "passed_by", cmp.make_compliance_checklist_item, "fk_compliance_checklist_items_passed_by"),
    (ComplianceGateStatus, "enabled_by", cmp.make_compliance_gate_status, "fk_compliance_gate_status_enabled_by"),
    (ContactChannel, "company_id", lds.make_contact_channel, "fk_contact_channels_company_id_companies"),
    (DuplicateCandidate, "decided_by", lds.make_duplicate_candidate, "fk_duplicate_candidates_decided_by_users"),
    (DuplicateCandidate, "person_a_id", lds.make_duplicate_candidate, "fk_duplicate_candidates_person_a_id_people"),
    (DuplicateCandidate, "person_b_id", lds.make_duplicate_candidate, "fk_duplicate_candidates_person_b_id_people"),
    (ErasureRecord, "erased_by", cmp.make_erasure_record, "fk_erasure_records_erased_by_users"),
    (ImportChange, "import_report_id", imp.make_import_change, "fk_import_changes_import_report_id_import_reports"),
    (ImportChange, "person_id", imp.make_import_change, "fk_import_changes_person_id_people"),
    (ImportFile, "source_profile_id", imp.make_import_file, "fk_import_files_source_profile_id_source_profiles"),
    (ImportFile, "uploaded_by", imp.make_import_file, "fk_import_files_uploaded_by_users"),
    (ImportReport, "import_file_id", imp.make_import_report, "fk_import_reports_import_file_id_files"),
    (LeadEvent, "actor_id", lds.make_lead_event, "fk_lead_events_actor_id_users"),
    (LeadEvent, "person_id", lds.make_lead_event, "fk_lead_events_person_id_people"),
    (LeadNote, "person_id", lds.make_lead_note, "fk_lead_notes_person_id_people"),
    (LeadStatusFlag, "person_id", lds.make_lead_status_flag, "fk_lead_status_flags_person_id_people"),
    (LeadStatusFlag, "set_by", lds.make_lead_status_flag, "fk_lead_status_flags_set_by_users"),
    (MergeRecord, "merged_by", lds.make_merge_record, "fk_merge_records_merged_by_users"),
    (MergeRecord, "survivor_id", lds.make_merge_record, "fk_merge_records_survivor_id_people"),
    (OptOut, "created_by", cmp.make_opt_out, "fk_opt_outs_created_by_users"),
    (OptOut, "removed_by", cmp.make_opt_out, "fk_opt_outs_removed_by_users"),
    (Person, "company_id", lds.make_person, "fk_people_company_id_companies"),
    (Person, "owner_id", lds.make_person, "fk_people_owner_id_users"),
    (PersonEmail, "person_id", lds.make_person_email, "fk_person_emails_person_id_people"),
    (PersonPhone, "person_id", lds.make_person_phone, "fk_person_phones_person_id_people"),
    (QuarantineRecord, "raw_row_id", lds.make_quarantine_record, "fk_quarantine_records_raw_row_id_raw_rows"),
    (QuarantineRecord, "resolved_by", lds.make_quarantine_record, "fk_quarantine_records_resolved_by_users"),
    (RawRow, "person_id", imp.make_raw_row, "fk_raw_rows_person_id_people"),
    (Segment, "owner_id", lds.make_segment, "fk_segments_owner_id_users"),
    (SocialProfile, "person_id", lds.make_social_profile, "fk_social_profiles_person_id_people"),
    (SourceProfile, "created_by", imp.make_source_profile, "fk_source_profiles_created_by_users"),
    (Touch, "person_id", lds.make_touch, "fk_touches_person_id_people"),
    (Touch, "rep_id", lds.make_touch, "fk_touches_rep_id_users"),
]  # fmt: skip

# Cases that need factory arguments or a specific missing id, keyed by constraint name.
FACTORY_KWARGS = {"fk_opt_outs_removed_by_users": OPT_OUT_REMOVED}
MISSING_IDS = {
    "fk_duplicate_candidates_person_a_id_people": LOWEST_UUID,
    "fk_duplicate_candidates_person_b_id_people": HIGHEST_UUID,
}

# (table, factory, SQL assignment, constraint) for fixed-value and sign CHECKs. The duplicate
# candidate sets decided_at too, because its status and decided_at CHECK would fail first.
CHECK_CASES = [
    ("companies", lds.make_company, "employee_count = -1", "ck_companies_employee_count_nonnegative"),
    ("companies", lds.make_company, "annual_revenue = -1", "ck_companies_annual_revenue_nonnegative"),
    ("companies", lds.make_company, "total_funding = -1", "ck_companies_total_funding_nonnegative"),
    ("contact_channels", lds.make_contact_channel, "channel_type = 'bogus'", "ck_contact_channels_channel_type_valid"),
    ("duplicate_candidates", lds.make_duplicate_candidate, "status = 'bogus', decided_at = now()", "ck_duplicate_candidates_status_valid"),
    ("person_emails", lds.make_person_email, "verification_status = 'bogus'", "ck_person_emails_verification_status_valid"),
    ("compliance_checklist_items", cmp.make_compliance_checklist_item, "item_key = 'bogus'", "ck_compliance_checklist_items_item_key_valid"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("model", "column", "factory", "constraint"),
    FOREIGN_KEY_CASES,
    ids=[case[3] for case in FOREIGN_KEY_CASES],
)
def test_foreign_key_rejects_a_missing_parent(
    db_session: Session,
    model: type,
    column: str,
    factory: Callable[..., object],
    constraint: str,
) -> None:
    """Pointing the column at an id that does not exist fails on that foreign key by name."""
    row = factory(db_session, **FACTORY_KWARGS.get(constraint, {}))
    missing_parent = MISSING_IDS.get(constraint, uuid.uuid4())
    with pytest.raises(IntegrityError, match=constraint), db_session.begin_nested():
        db_session.execute(update(model).where(model.id == row.id).values({column: missing_parent}))


@pytest.mark.parametrize(
    ("table", "factory", "assignment", "constraint"),
    CHECK_CASES,
    ids=[case[3] for case in CHECK_CASES],
)
def test_check_constraint_rejects_an_invalid_value(
    db_session: Session,
    table: str,
    factory: Callable[..., object],
    assignment: str,
    constraint: str,
) -> None:
    """Writing an invalid value (negative number or unknown code) fails on that CHECK by name."""
    row = factory(db_session)
    with pytest.raises(IntegrityError, match=constraint), db_session.begin_nested():
        # Plain SQL on purpose: the ORM would refuse an unknown code before PostgreSQL sees it.
        db_session.execute(text(f"UPDATE {table} SET {assignment} WHERE id = :id"), {"id": row.id})
