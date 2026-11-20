"""Tests for the imports tables: constraints, delete rules and the raw_rows immutability guard.

Needed because the schema is the only thing protecting raw import rows (D-099), the duplicate-
file warning (D-109) and the report counts (D-050) until the M2 services exist. Runs against
real PostgreSQL through the shared db_session fixture; all data is synthetic (M1 task A4).
"""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.models import User
from app.imports.models import (
    REPORT_COUNT_COLUMNS,
    ColumnMapping,
    ImportChange,
    ImportFile,
    ImportReport,
    ImportStatus,
    RawRow,
    SourceProfile,
)
from app.leads.models import Person, QuarantineRecord

SHA_A = "a" * 64
SHA_B = "b" * 64

Rejected = Callable[[object, str], None]


@pytest.fixture
def import_file(db_session: Session, user: User) -> ImportFile:
    """Insert and return a synthetic import file uploaded by the synthetic user."""
    file = ImportFile(sha256=SHA_A, filename="leads.csv", uploaded_by=user.id)
    db_session.add(file)
    db_session.flush()
    return file


@pytest.fixture
def raw_row(db_session: Session, import_file: ImportFile) -> RawRow:
    """Insert and return a synthetic raw row (row 1) of the synthetic import file."""
    row = RawRow(
        import_file_id=import_file.id,
        row_number=1,
        original_values={"Email": "Jane@Example.com", "First Name": "Jane"},
        email_normalized="jane@example.com",
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def report(db_session: Session, import_file: ImportFile) -> ImportReport:
    """Insert and return a synthetic report for the synthetic import file."""
    report = ImportReport(import_file_id=import_file.id)
    db_session.add(report)
    db_session.flush()
    return report


# --- import_files and source_profiles ---


def test_import_file_defaults(import_file: ImportFile, db_session: Session) -> None:
    """A new import file starts as 'uploaded' with row_count 0 and no profile or country."""
    db_session.refresh(import_file)

    assert import_file.status is ImportStatus.UPLOADED
    assert import_file.row_count == 0
    assert import_file.source_profile_id is None
    assert import_file.default_country is None


def test_same_sha256_can_be_uploaded_twice(db_session: Session, import_file: ImportFile) -> None:
    """Identical content may be imported again after the warning (D-109): sha256 is not unique."""
    db_session.add(ImportFile(sha256=import_file.sha256, filename="leads-again.csv"))
    db_session.flush()

    matches = db_session.scalars(select(ImportFile.id).where(ImportFile.sha256 == SHA_A)).all()
    assert len(matches) == 2


@pytest.mark.parametrize("bad_sha", ["abc", "A" * 64, "g" * 64])
def test_sha256_must_be_lowercase_hex_digest(assert_rejected: Rejected, bad_sha: str) -> None:
    """A short, uppercase or non-hex digest is rejected by ck_import_files_sha256_hex."""
    assert_rejected(ImportFile(sha256=bad_sha, filename="x.csv"), "ck_import_files_sha256_hex")


def test_import_file_rejects_unknown_status(db_session: Session, import_file: ImportFile) -> None:
    """A status outside the ImportStatus list is rejected by the CHECK constraint."""
    # Raw SQL: the Enum column type would refuse an unknown value before the database sees it.
    with (
        pytest.raises(IntegrityError, match="ck_import_files_status_valid"),
        db_session.begin_nested(),
    ):
        db_session.execute(
            text("UPDATE import_files SET status = 'bogus' WHERE id = :id"), {"id": import_file.id}
        )


def test_import_file_rejects_negative_row_count(assert_rejected: Rejected) -> None:
    """A negative row_count is rejected by ck_import_files_row_count_nonnegative."""
    assert_rejected(
        ImportFile(sha256=SHA_A, filename="x.csv", row_count=-1),
        "ck_import_files_row_count_nonnegative",
    )


def test_source_profile_name_is_unique(db_session: Session, assert_rejected: Rejected) -> None:
    """Two profiles cannot share a name; layout is free text and mapping_defaults defaults to {}."""
    profile = SourceProfile(name="Apollo export", layout="apollo")
    db_session.add(profile)
    db_session.flush()
    db_session.refresh(profile)

    assert profile.mapping_defaults == {}
    assert profile.is_active is True
    assert_rejected(SourceProfile(name="Apollo export", layout="other"), "uq_source_profiles_name")


def test_deleting_a_profile_keeps_the_file(db_session: Session, import_file: ImportFile) -> None:
    """Deleting a source profile sets import_files.source_profile_id to NULL (SET NULL)."""
    profile = SourceProfile(name="Manual list", layout="manual")
    db_session.add(profile)
    db_session.flush()
    db_session.execute(
        update(ImportFile)
        .where(ImportFile.id == import_file.id)
        .values(source_profile_id=profile.id)
    )

    db_session.execute(delete(SourceProfile).where(SourceProfile.id == profile.id))
    db_session.refresh(import_file)

    assert import_file.source_profile_id is None


# --- column_mappings ---


def test_column_mapping_is_unique_per_file_and_index(
    db_session: Session, import_file: ImportFile, assert_rejected: Rejected
) -> None:
    """A column index can be mapped once per file; a header-less column (NULL header) is valid."""
    db_session.add(ColumnMapping(import_file_id=import_file.id, column_index=0, source_header=None))
    db_session.flush()

    assert_rejected(
        ColumnMapping(import_file_id=import_file.id, column_index=0, target_field="first_name"),
        "uq_column_mappings_import_file_id_column_index",
    )


def test_column_mapping_rejects_negative_index(
    import_file: ImportFile, assert_rejected: Rejected
) -> None:
    """A negative column index is rejected by ck_column_mappings_column_index_nonnegative."""
    assert_rejected(
        ColumnMapping(import_file_id=import_file.id, column_index=-1),
        "ck_column_mappings_column_index_nonnegative",
    )


# --- raw_rows: constraints and delete rules ---


def test_raw_row_number_is_unique_per_file(raw_row: RawRow, assert_rejected: Rejected) -> None:
    """The same row number cannot be stored twice for one file."""
    assert_rejected(
        RawRow(import_file_id=raw_row.import_file_id, row_number=1, original_values={}),
        "uq_raw_rows_import_file_id_row_number",
    )


def test_raw_row_number_starts_at_one(import_file: ImportFile, assert_rejected: Rejected) -> None:
    """Row number 0 is rejected: rows are numbered from 1."""
    assert_rejected(
        RawRow(import_file_id=import_file.id, row_number=0, original_values={}),
        "ck_raw_rows_row_number_positive",
    )


def test_raw_row_email_must_be_lowercase(
    import_file: ImportFile, assert_rejected: Rejected
) -> None:
    """A mixed-case email_normalized is rejected so erase-person lookups cannot miss rows."""
    assert_rejected(
        RawRow(
            import_file_id=import_file.id,
            row_number=1,
            original_values={},
            email_normalized="Jane@Example.com",
        ),
        "ck_raw_rows_email_normalized_lowercase",
    )


def test_file_with_raw_rows_cannot_be_deleted(db_session: Session, raw_row: RawRow) -> None:
    """RESTRICT: deleting an import file that still has raw rows fails."""
    with (
        pytest.raises(IntegrityError, match="fk_raw_rows_import_file_id_import_files"),
        db_session.begin_nested(),
    ):
        db_session.execute(delete(ImportFile).where(ImportFile.id == raw_row.import_file_id))


def test_deleting_a_person_unlinks_the_raw_row(
    db_session: Session, raw_row: RawRow, person: Person
) -> None:
    """Deleting a person keeps the raw row and sets person_id to NULL; the guard allows it."""
    db_session.execute(update(RawRow).where(RawRow.id == raw_row.id).values(person_id=person.id))

    db_session.execute(delete(Person).where(Person.id == person.id))
    db_session.refresh(raw_row)

    assert raw_row.person_id is None
    assert raw_row.original_values["First Name"] == "Jane"


# --- raw_rows: the immutability guard (D-099, D-008) ---


@pytest.mark.parametrize(
    "changes",
    [
        {"original_values": {"Email": "changed@example.com"}},
        {"email_normalized": "other@example.com"},
        {"row_number": 2},
        {"import_file_id": uuid.uuid4()},
    ],
    ids=["original_values", "email_normalized", "row_number", "import_file_id"],
)
def test_update_of_original_columns_is_rejected(
    db_session: Session, raw_row: RawRow, changes: dict[str, object]
) -> None:
    """Changing any original column raises the guard error and leaves the row as it was."""
    with pytest.raises(DBAPIError, match="raw_rows is immutable"), db_session.begin_nested():
        db_session.execute(update(RawRow).where(RawRow.id == raw_row.id).values(**changes))

    db_session.refresh(raw_row)
    assert raw_row.row_number == 1
    assert raw_row.original_values["First Name"] == "Jane"


def test_person_link_can_change(db_session: Session, raw_row: RawRow, person: Person) -> None:
    """Release or merge may relink a raw row: updating only person_id is allowed."""
    db_session.execute(update(RawRow).where(RawRow.id == raw_row.id).values(person_id=person.id))
    db_session.refresh(raw_row)

    assert raw_row.person_id == person.id


def test_raw_row_can_be_deleted_for_erase_person(db_session: Session, raw_row: RawRow) -> None:
    """DELETE stays allowed: erase-person removes the original rows (D-099)."""
    db_session.execute(delete(RawRow).where(RawRow.id == raw_row.id))

    assert db_session.scalar(select(RawRow.id).where(RawRow.id == raw_row.id)) is None


# --- import_reports and import_changes ---


def test_report_counts_default_to_zero(report: ImportReport, db_session: Session) -> None:
    """A new report has all seven counts at 0 and an empty failure_reasons object."""
    db_session.refresh(report)

    assert [getattr(report, column) for column in REPORT_COUNT_COLUMNS] == [0] * 7
    assert report.failure_reasons == {}


def test_one_report_per_file(report: ImportReport, assert_rejected: Rejected) -> None:
    """A second report for the same import file is rejected."""
    assert_rejected(
        ImportReport(import_file_id=report.import_file_id), "uq_import_reports_import_file_id"
    )


@pytest.mark.parametrize("column", REPORT_COUNT_COLUMNS)
def test_report_counts_cannot_be_negative(
    import_file: ImportFile, assert_rejected: Rejected, column: str
) -> None:
    """Each D-050 total is rejected when negative, by its own CHECK constraint."""
    assert_rejected(
        ImportReport(import_file_id=import_file.id, **{column: -1}),
        f"ck_import_reports_{column}_nonnegative",
    )


def test_deleting_a_file_removes_its_report_and_mappings(
    db_session: Session, report: ImportReport
) -> None:
    """CASCADE: deleting a file (that has no raw rows) removes its report and mappings."""
    db_session.add(ColumnMapping(import_file_id=report.import_file_id, column_index=0))
    db_session.flush()

    db_session.execute(delete(ImportFile).where(ImportFile.id == report.import_file_id))

    assert db_session.scalar(select(ImportReport.id)) is None
    assert db_session.scalar(select(ColumnMapping.id)) is None


def test_change_summary_is_unique_per_report_and_person(
    db_session: Session, report: ImportReport, person: Person, assert_rejected: Rejected
) -> None:
    """One change summary per updated person per import; a second one is rejected."""
    db_session.add(
        ImportChange(
            import_report_id=report.id,
            person_id=person.id,
            changes={"title": {"old": "CTO", "new": "CEO"}},
        )
    )
    db_session.flush()

    assert_rejected(
        ImportChange(import_report_id=report.id, person_id=person.id, changes={}),
        "uq_import_changes_import_report_id_person_id",
    )


def test_deleting_a_person_removes_their_change_summaries(
    db_session: Session, report: ImportReport, person: Person
) -> None:
    """CASCADE: erase-person removes the old and new values held in import_changes."""
    db_session.add(ImportChange(import_report_id=report.id, person_id=person.id, changes={}))
    db_session.flush()

    db_session.execute(delete(Person).where(Person.id == person.id))

    assert db_session.scalar(select(ImportChange.id)) is None


# --- quarantine_records.raw_row_id (added by 0007) ---


def test_quarantine_record_links_to_one_raw_row_at_most(
    db_session: Session, raw_row: RawRow, assert_rejected: Rejected
) -> None:
    """Each raw row has at most one quarantine record; records without a raw row are allowed."""
    db_session.add(QuarantineRecord(payload={}, raw_row_id=raw_row.id))
    db_session.add(QuarantineRecord(payload={}))
    db_session.add(QuarantineRecord(payload={}))
    db_session.flush()

    assert_rejected(
        QuarantineRecord(payload={}, raw_row_id=raw_row.id), "uq_quarantine_records_raw_row_id"
    )


def test_deleting_a_raw_row_removes_its_quarantine_record(
    db_session: Session, raw_row: RawRow
) -> None:
    """CASCADE: erase-person deleting the raw row also removes its quarantine payload."""
    db_session.add(QuarantineRecord(payload={"Email": "Jane@Example.com"}, raw_row_id=raw_row.id))
    db_session.flush()

    db_session.execute(delete(RawRow).where(RawRow.id == raw_row.id))

    assert db_session.scalar(select(QuarantineRecord.id)) is None
