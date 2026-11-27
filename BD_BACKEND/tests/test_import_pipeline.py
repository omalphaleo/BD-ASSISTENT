"""Tests for the import pipeline (M2-A3) on a real PostgreSQL database, with a fake ingest_row.

Needed because the pipeline's promises meet here: the original row is stored before anything
else (D-099), every outcome is counted into the report (D-050), a bad row never fails the file
(D-068), a crashed run resumes without duplicates or double counts, and owner names map to users
without taking a lead from its owner (D-075). W2's real ingest_row does not exist yet, so a fake
records its calls and returns scripted outcomes. All data is synthetic.
"""

from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest
from factories.core import make_user
from factories.imports import make_column_mapping, make_import_file
from factories.leads import make_person
from import_files import csv_bytes
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.audit.services import AuditAction
from app.config import get_settings
from app.core.models import User
from app.imports.models import ColumnMapping, ImportFile, ImportReport, ImportStatus, RawRow
from app.imports.parsers import UploadLimits, limits_from_settings
from app.imports.pipeline import INGEST_ERROR_REASON, run_import
from app.imports.storage import LocalDiskStorage, new_storage_key
from app.leads.contracts import ImportContext, RowOutcome, RowOutcomeKind, SourceRow
from app.leads.models import Person

HEADER = ["First Name", "Last Name", "Email", "Owner"]
# Column index to target field key, as the mapping step would save it.
MAPPING = {0: "first_name", 1: "last_name", 2: "email", 3: "owner_name"}


class WorkerCrash(BaseException):
    """Stands in for a killed worker: not an Exception, so no per-row handler may swallow it."""


class FakeIngest:
    """A stand-in for W2's ingest_row that records calls and returns scripted outcomes.

    Attributes:
        calls: The SourceRows it received, in order.
        script: Optional function from a row to its RowOutcome (default: IMPORTED).
    """

    def __init__(self, script: Callable[[SourceRow], RowOutcome] | None = None) -> None:
        self.calls: list[SourceRow] = []
        self.contexts: list[ImportContext] = []
        self._script = script or (lambda row: RowOutcome(kind=RowOutcomeKind.IMPORTED))

    def __call__(self, session: Session, row: SourceRow, ctx: ImportContext) -> RowOutcome:
        """Record the call and return the scripted outcome (or raise what the script raises)."""
        self.calls.append(row)
        self.contexts.append(ctx)
        return self._script(row)


@pytest.fixture
def storage(tmp_path: Path) -> LocalDiskStorage:
    """A throwaway upload directory, so tests never touch a real volume."""
    return LocalDiskStorage(tmp_path / "uploads")


@pytest.fixture
def limits() -> UploadLimits:
    """The upload limits from the current settings."""
    return limits_from_settings(get_settings())


def _rows(count: int, owner: str = "") -> list[list[str]]:
    """Header plus count synthetic people."""
    return [HEADER] + [
        [f"First{n}", f"Last{n}", f"Person{n}@Example.com", owner] for n in range(count)
    ]


def _make_import(
    db: Session,
    storage: LocalDiskStorage,
    rows: list[list[str]],
    *,
    status: ImportStatus = ImportStatus.PROCESSING,
    uploaded_by: User | None = None,
) -> ImportFile:
    """Store a CSV and create its ImportFile with a saved mapping, ready to be processed."""
    key = new_storage_key("csv")
    content = csv_bytes(rows)
    storage.save(key, BytesIO(content))
    import_file = make_import_file(
        db,
        storage_key=key,
        size_bytes=len(content),
        row_count=len(rows) - 1,
        status=status,
        uploaded_by=(uploaded_by or make_user(db)).id,
    )
    for index, target in MAPPING.items():
        make_column_mapping(
            db,
            import_file=import_file,
            column_index=index,
            source_header=HEADER[index],
            target_field=target,
        )
    # Commit like the upload and mapping steps do: the job runs in its own session and may
    # roll back its open chunk, which must never undo the import's own setup.
    db.commit()
    return import_file


def _run(db: Session, import_file: ImportFile, storage, limits, ingest, chunk_size: int = 500):
    """Run the pipeline for the import with the given fake."""
    run_import(
        db, import_file.id, storage=storage, limits=limits, ingest_row=ingest, chunk_size=chunk_size
    )


def _report(db: Session, import_file: ImportFile) -> ImportReport:
    """Reload the import's report."""
    db.expire_all()
    return db.scalars(
        select(ImportReport).where(ImportReport.import_file_id == import_file.id)
    ).one()


def import_file_mappings(db: Session, import_file: ImportFile) -> list[ColumnMapping]:
    """The saved column mappings of an import."""
    return list(
        db.scalars(select(ColumnMapping).where(ColumnMapping.import_file_id == import_file.id))
    )


def _actions(db: Session) -> list[str]:
    """Audit actions recorded so far."""
    return [row.action for row in db.scalars(select(AuditLog).order_by(AuditLog.occurred_at))]


def _raw_count(db: Session, import_file: ImportFile) -> int:
    """How many raw rows the import has stored."""
    return db.scalar(
        select(func.count()).select_from(RawRow).where(RawRow.import_file_id == import_file.id)
    )


def test_every_outcome_is_counted_and_the_import_completes(
    db_session: Session, storage: LocalDiskStorage, limits: UploadLimits
) -> None:
    """Each RowOutcomeKind lands in its own report counter and the import is COMPLETED."""
    kinds = list(RowOutcomeKind)
    import_file = _make_import(db_session, storage, _rows(len(kinds)))
    ingest = FakeIngest(
        lambda row: RowOutcome(kind=kinds[row.row_number - 2], reason_code="some_reason")
    )

    _run(db_session, import_file, storage, limits, ingest)

    report = _report(db_session, import_file)
    assert (
        report.received,
        report.imported,
        report.updated,
        report.unchanged,
        report.duplicates_found,
        report.quarantined,
        report.rejected,
    ) == (6, 1, 1, 1, 1, 1, 1)
    # Only quarantined and rejected rows carry a failure reason (D-050).
    assert report.failure_reasons == {"some_reason": 2}
    assert db_session.get(ImportFile, import_file.id).status is ImportStatus.COMPLETED
    assert _actions(db_session)[-1] == AuditAction.IMPORT_FINISHED.value


def test_source_row_carries_the_mapping_and_the_import_context(
    db_session: Session, storage: LocalDiskStorage, limits: UploadLimits
) -> None:
    """ingest_row receives mapped values, the raw email text, the file settings and the context."""
    import_file = _make_import(db_session, storage, _rows(1))
    import_file.default_country = "Ireland"
    ingest = FakeIngest()

    _run(db_session, import_file, storage, limits, ingest)

    (row,) = ingest.calls
    assert row.row_number == 2
    assert row.values["first_name"] == "First0"
    assert row.values["email"] == "Person0@Example.com"
    assert row.raw_email == "Person0@Example.com"  # exactly as in the file
    assert row.import_file_id == import_file.id
    assert row.default_country == "Ireland"
    (context,) = ingest.contexts
    assert context.uploaded_by == import_file.uploaded_by
    assert context.source.value == "import"


def test_ten_percent_bad_rows_do_not_fail_the_file(
    db_session: Session, storage: LocalDiskStorage, limits: UploadLimits
) -> None:
    """One row in ten raises: the other 90% import, the file completes, bad ones are rejected."""

    def script(row: SourceRow) -> RowOutcome:
        if row.row_number % 10 == 0:
            raise ValueError("boom")
        return RowOutcome(kind=RowOutcomeKind.IMPORTED)

    import_file = _make_import(db_session, storage, _rows(100))
    _run(db_session, import_file, storage, limits, FakeIngest(script), chunk_size=25)

    report = _report(db_session, import_file)
    assert (report.received, report.imported, report.rejected) == (100, 90, 10)
    assert report.failure_reasons == {INGEST_ERROR_REASON: 10}
    assert db_session.get(ImportFile, import_file.id).status is ImportStatus.COMPLETED


def test_a_large_file_is_processed_across_many_chunks(
    db_session: Session, storage: LocalDiskStorage, limits: UploadLimits
) -> None:
    """2,000 rows in chunks of 150: every row is ingested once and the totals are exact."""
    import_file = _make_import(db_session, storage, _rows(2000))
    ingest = FakeIngest()

    _run(db_session, import_file, storage, limits, ingest, chunk_size=150)

    assert len(ingest.calls) == 2000
    assert _report(db_session, import_file).imported == 2000
    assert _raw_count(db_session, import_file) == 2000


def test_raw_rows_are_kept_unmodified_even_for_failed_rows(
    db_session: Session, storage: LocalDiskStorage, limits: UploadLimits
) -> None:
    """Every row, including the one whose ingest raised, has a raw row with its original values."""

    def script(row: SourceRow) -> RowOutcome:
        if row.row_number == 3:
            raise RuntimeError("boom")
        return RowOutcome(kind=RowOutcomeKind.IMPORTED)

    import_file = _make_import(db_session, storage, _rows(3))
    _run(db_session, import_file, storage, limits, FakeIngest(script))

    raw = {
        r.row_number: r
        for r in db_session.scalars(select(RawRow).where(RawRow.import_file_id == import_file.id))
    }
    assert sorted(raw) == [2, 3, 4]
    assert raw[3].original_values == {
        "First Name": "First1",
        "Last Name": "Last1",
        "Email": "Person1@Example.com",
        "Owner": "",
    }
    assert raw[3].email_normalized == "person1@example.com"


def test_raw_row_is_linked_to_the_person_ingest_returned(
    db_session: Session, storage: LocalDiskStorage, limits: UploadLimits
) -> None:
    """When ingest_row returns a person_id, the raw row's person_id is set to it."""
    person = make_person(db_session)
    import_file = _make_import(db_session, storage, _rows(1))
    ingest = FakeIngest(lambda row: RowOutcome(RowOutcomeKind.IMPORTED, person_id=person.id))

    _run(db_session, import_file, storage, limits, ingest)

    assert db_session.scalars(select(RawRow.person_id)).one() == person.id


def test_rerun_after_a_worker_crash_gives_the_same_result(
    db_session: Session, storage: LocalDiskStorage, limits: UploadLimits
) -> None:
    """A crash mid-file, then a re-run: same totals as a clean run, one raw row per row."""
    crash_at = 7
    state = {"crash": True}

    def script(row: SourceRow) -> RowOutcome:
        if state["crash"] and row.row_number == crash_at:
            raise WorkerCrash
        return RowOutcome(kind=RowOutcomeKind.IMPORTED)

    import_file = _make_import(db_session, storage, _rows(12))
    with pytest.raises(WorkerCrash):
        _run(db_session, import_file, storage, limits, FakeIngest(script), chunk_size=5)
    db_session.rollback()  # a new worker starts with a fresh session: the open chunk is lost

    # Chunk one (rows 2-6) was committed; the chunk holding row 7 was not.
    assert _raw_count(db_session, import_file) == 5
    assert _report(db_session, import_file).received == 5

    state["crash"] = False
    rerun = FakeIngest(script)
    _run(db_session, import_file, storage, limits, rerun, chunk_size=5)

    assert [row.row_number for row in rerun.calls] == list(range(7, 14))  # resumed, no repeats
    report = _report(db_session, import_file)
    assert (report.received, report.imported) == (12, 12)
    assert _raw_count(db_session, import_file) == 12
    assert db_session.get(ImportFile, import_file.id).status is ImportStatus.COMPLETED


def test_running_a_completed_import_again_does_nothing(
    db_session: Session, storage: LocalDiskStorage, limits: UploadLimits
) -> None:
    """A second run of a COMPLETED import calls nothing and changes no counter."""
    import_file = _make_import(db_session, storage, _rows(3))
    _run(db_session, import_file, storage, limits, FakeIngest())
    again = FakeIngest()

    _run(db_session, import_file, storage, limits, again)

    assert again.calls == []
    assert _report(db_session, import_file).received == 3


def test_an_import_that_was_not_started_is_left_alone(
    db_session: Session, storage: LocalDiskStorage, limits: UploadLimits
) -> None:
    """A job for an import still in MAPPING is ignored: no rows stored, status unchanged."""
    import_file = _make_import(db_session, storage, _rows(2), status=ImportStatus.MAPPING)
    ingest = FakeIngest()

    _run(db_session, import_file, storage, limits, ingest)

    assert ingest.calls == []
    assert _raw_count(db_session, import_file) == 0
    assert db_session.get(ImportFile, import_file.id).status is ImportStatus.MAPPING


def test_a_missing_stored_file_fails_the_import_with_an_audit_event(
    db_session: Session, storage: LocalDiskStorage, limits: UploadLimits
) -> None:
    """The stored file is gone: the import ends FAILED and import.failed records a reason code."""
    import_file = _make_import(db_session, storage, _rows(2))
    storage.delete(import_file.storage_key)

    _run(db_session, import_file, storage, limits, FakeIngest())

    assert db_session.get(ImportFile, import_file.id).status is ImportStatus.FAILED
    failure = db_session.scalars(
        select(AuditLog).where(AuditLog.action == AuditAction.IMPORT_FAILED.value)
    ).one()
    assert failure.summary == {"reason": "storage_error"}


def test_a_failed_import_that_is_requeued_resumes_at_the_cursor(
    db_session: Session, storage: LocalDiskStorage, limits: UploadLimits
) -> None:
    """After a FAILED run, running again (file restored) processes only the missing rows."""
    import_file = _make_import(db_session, storage, _rows(4))
    import_file.status = ImportStatus.FAILED
    db_session.commit()
    ingest = FakeIngest()

    _run(db_session, import_file, storage, limits, ingest)

    assert len(ingest.calls) == 4
    assert db_session.get(ImportFile, import_file.id).status is ImportStatus.COMPLETED


def test_missing_mapping_fails_the_import(
    db_session: Session, storage: LocalDiskStorage, limits: UploadLimits
) -> None:
    """No saved mapping at run time: FAILED with the mapping_not_saved reason, nothing ingested."""
    import_file = _make_import(db_session, storage, _rows(2))
    for mapping in import_file_mappings(db_session, import_file):
        db_session.delete(mapping)
    db_session.commit()
    ingest = FakeIngest()

    _run(db_session, import_file, storage, limits, ingest)

    assert ingest.calls == []
    assert db_session.get(ImportFile, import_file.id).status is ImportStatus.FAILED


def test_owner_is_assigned_only_when_the_person_has_none(
    db_session: Session, storage: LocalDiskStorage, limits: UploadLimits
) -> None:
    """A matched owner name fills an empty owner_id and never replaces an owner (D-075)."""
    jane = make_user(db_session, email="jane.doe@example.com")
    other = make_user(db_session, email="other@example.com")
    unowned = make_person(db_session)
    owned = make_person(db_session, owner_id=other.id)
    people = iter([unowned, owned])
    import_file = _make_import(db_session, storage, _rows(2, owner="Jane Doe"))
    ingest = FakeIngest(lambda row: RowOutcome(RowOutcomeKind.UPDATED, person_id=next(people).id))

    _run(db_session, import_file, storage, limits, ingest)

    db_session.expire_all()
    assert db_session.get(Person, unowned.id).owner_id == jane.id
    assert db_session.get(Person, owned.id).owner_id == other.id


def test_unknown_owner_leaves_the_person_unassigned(
    db_session: Session, storage: LocalDiskStorage, limits: UploadLimits
) -> None:
    """An owner name that matches no user leaves owner_id empty (the Unassigned pool)."""
    person = make_person(db_session)
    import_file = _make_import(db_session, storage, _rows(1, owner="Nobody Known"))
    ingest = FakeIngest(lambda row: RowOutcome(RowOutcomeKind.IMPORTED, person_id=person.id))

    _run(db_session, import_file, storage, limits, ingest)

    db_session.expire_all()
    assert db_session.get(Person, person.id).owner_id is None


def test_pipeline_audit_and_logs_hold_no_lead_data(
    db_session: Session,
    storage: LocalDiskStorage,
    limits: UploadLimits,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing row logs its number and exception type only, never the email or name."""

    def script(row: SourceRow) -> RowOutcome:
        raise ValueError(f"cannot handle {row.raw_email}")

    import_file = _make_import(db_session, storage, _rows(1))
    with caplog.at_level("WARNING"):
        _run(db_session, import_file, storage, limits, FakeIngest(script))

    assert "ValueError" in caplog.text
    assert "example.com" not in caplog.text
    assert all(
        "example.com" not in str(row.summary) for row in db_session.scalars(select(AuditLog))
    )
