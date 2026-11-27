"""The import pipeline: start an import, then process its file in chunks (M2-A3).

Needed so a mapped file becomes leads without freezing the page and without one bad row
failing the file (D-068). For every row the pipeline stores the untouched RawRow first
(D-099), builds a SourceRow from the saved mapping, hands it to W2's ingest_row (injected, so
tests use a fake) and counts the RowOutcome into the ImportReport. It never validates, matches
or merges (that is W2). Used by the process_import task (imports.tasks) and the start route.

Resume and idempotency: one chunk is one transaction holding its raw rows, whatever ingest_row
wrote and the report counters, so they commit or roll back together. A re-run after a crash
continues after the highest stored raw row number and cannot double-count.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.audit.services import AuditAction, record
from app.config import get_settings
from app.core import clock
from app.core.models import User
from app.imports.access import can_change_import
from app.imports.conversion import FieldFormat
from app.imports.errors import (
    ImportNotFoundError,
    MappingRejectedError,
    StartErrorKind,
    StartRejectedError,
    StorageError,
    UploadRejectedError,
)
from app.imports.mapping import (
    MappedColumn,
    apply_mapping,
    import_formats,
    mapped_columns,
    open_import_records,
)
from app.imports.models import ImportFile, ImportReport, ImportStatus, RawRow
from app.imports.owners import OwnerIndex, assign_owner_if_empty, build_owner_index, resolve_owner
from app.imports.parsers import UploadLimits
from app.imports.raw_keys import original_value_keys
from app.imports.storage import FileStorage
from app.imports.upload import EDITABLE_STATUSES, get_import_for_viewer
from app.leads.contracts import (
    REQUIRED_FIELD_KEYS,
    ImportContext,
    IngestRow,
    IngestSource,
    RowOutcome,
    RowOutcomeKind,
    SourceRow,
)

logger = logging.getLogger(__name__)

NOT_STARTABLE_MESSAGE = "This import cannot be started."
ALREADY_PROCESSING_MESSAGE = "This import is already being processed."
MAPPING_INCOMPLETE_MESSAGE = "Save a column mapping that covers the required fields first."

# failure_reasons key for a row whose ingest_row call raised (a bug or a data surprise).
INGEST_ERROR_REASON = "ingest_error"
UNSPECIFIED_REASON = "unspecified"
EMAIL_NORMALIZED_MAX_LENGTH = 320
REASON_CODE_MAX_LENGTH = 64  # raw_rows.reason_code

# Which ImportReport counter each outcome adds to (the seven D-050 totals).
_COUNTER_BY_OUTCOME: dict[RowOutcomeKind, str] = {
    RowOutcomeKind.IMPORTED: "imported",
    RowOutcomeKind.UPDATED: "updated",
    RowOutcomeKind.UNCHANGED: "unchanged",
    RowOutcomeKind.POSSIBLE_DUPLICATE: "duplicates_found",
    RowOutcomeKind.QUARANTINED: "quarantined",
    RowOutcomeKind.REJECTED: "rejected",
}
# Only these outcomes carry a reason code worth counting in failure_reasons (D-050).
_FAILURE_OUTCOMES = frozenset({RowOutcomeKind.QUARANTINED, RowOutcomeKind.REJECTED})

Record = tuple[int, list[object]]


@dataclass(frozen=True, slots=True)
class _RunSettings:
    """What process_chunk needs besides the rows: the mapping, owners and the ingest function."""

    import_file: ImportFile
    report: ImportReport
    columns: Sequence[MappedColumn]
    formats: Mapping[str, FieldFormat]
    headers: Sequence[str]
    owners: OwnerIndex
    ingest_row: IngestRow
    context: ImportContext


# --- starting an import -----------------------------------------------------------------------


def start_import(
    db: Session, actor: User, import_id: uuid.UUID, *, ip_address: str | None = None
) -> ImportFile:
    """Move an import to PROCESSING and create its report; the caller then queues the job.

    Only the uploader may start, once, with a saved mapping that covers the mandatory fields
    (D-069). The state change and the audit event are committed here, before the job exists.

    Raises:
        ImportNotFoundError: If the import is missing or not visible to the actor.
        StartRejectedError: NOT_STARTABLE (not the uploader, or already finished or failed),
            ALREADY_PROCESSING, or MAPPING_INCOMPLETE (no saved mapping, a mandatory field
            unmapped, or a multi-sheet workbook with no chosen sheet).
    """
    import_file = get_import_for_viewer(db, actor, import_id)
    if not can_change_import(actor, import_file):
        raise StartRejectedError(StartErrorKind.NOT_STARTABLE, NOT_STARTABLE_MESSAGE)
    if import_file.status is ImportStatus.PROCESSING:
        raise StartRejectedError(StartErrorKind.ALREADY_PROCESSING, ALREADY_PROCESSING_MESSAGE)
    if import_file.status not in EDITABLE_STATUSES:
        raise StartRejectedError(StartErrorKind.NOT_STARTABLE, NOT_STARTABLE_MESSAGE)
    _require_complete_mapping(db, import_file)

    import_file.status = ImportStatus.PROCESSING
    _get_or_create_report(db, import_file.id)
    record(
        db,
        action=AuditAction.IMPORT_STARTED,
        actor_user_id=actor.id,
        object_type="import_file",
        object_id=str(import_file.id),
        summary={"row_count": import_file.row_count},
        ip_address=ip_address,
    )
    db.commit()
    return import_file


def _require_complete_mapping(db: Session, import_file: ImportFile) -> None:
    """Refuse to start without a saved mapping that covers REQUIRED_FIELD_KEYS.

    Raises:
        StartRejectedError: MAPPING_INCOMPLETE.
    """
    try:
        targets = {column.target_field for column in mapped_columns(db, import_file.id)}
    except MappingRejectedError as error:
        raise StartRejectedError(
            StartErrorKind.MAPPING_INCOMPLETE, MAPPING_INCOMPLETE_MESSAGE
        ) from error
    needs_sheet = (import_file.storage_key or "").endswith(
        ".xlsx"
    ) and import_file.worksheet is None
    if needs_sheet or not set(REQUIRED_FIELD_KEYS) <= targets:
        raise StartRejectedError(StartErrorKind.MAPPING_INCOMPLETE, MAPPING_INCOMPLETE_MESSAGE)


def _get_or_create_report(db: Session, import_id: uuid.UUID) -> ImportReport:
    """Return the import's single ImportReport, creating the zeroed one on first use."""
    report = db.scalar(select(ImportReport).where(ImportReport.import_file_id == import_id))
    if report is None:
        report = ImportReport(import_file_id=import_id, failure_reasons={})
        db.add(report)
        db.flush()
    return report


# --- running the import -----------------------------------------------------------------------


def run_import(
    db: Session,
    import_id: uuid.UUID,
    *,
    storage: FileStorage,
    limits: UploadLimits,
    ingest_row: IngestRow,
    chunk_size: int | None = None,
) -> None:
    """Process the whole file in chunks, resuming after the last stored raw row.

    A COMPLETED import is a no-op; one that was never started is left alone. A FAILED import
    (re-queued by an admin after fixing the cause) resumes at the cursor. A file-level problem
    (stored file gone or unreadable, mapping gone) ends the import as FAILED with an
    import.failed audit event. A failure inside one row never stops the file (D-068). Any other
    error (for example the database going away) propagates and leaves the import PROCESSING, so
    re-running the task resumes where the last committed chunk ended.

    Raises:
        ImportNotFoundError: If the import does not exist.
    """
    import_file = db.get(ImportFile, import_id)
    if import_file is None:
        raise ImportNotFoundError
    if import_file.status is ImportStatus.COMPLETED:
        return
    if import_file.status in EDITABLE_STATUSES:
        logger.warning("import %s was not started; process_import ignored", import_id)
        return
    if import_file.status is ImportStatus.FAILED:
        import_file.status = ImportStatus.PROCESSING

    chunk_size = chunk_size or get_settings().import_chunk_size
    try:
        _process_file(db, import_file, storage, limits, ingest_row, chunk_size)
    except (MappingRejectedError, UploadRejectedError) as error:
        db.rollback()
        _fail_import(db, import_id, error.kind.value)
        return
    except StorageError:
        db.rollback()
        _fail_import(db, import_id, "storage_error")
        return
    _finish_import(db, import_id)


def _process_file(
    db: Session,
    import_file: ImportFile,
    storage: FileStorage,
    limits: UploadLimits,
    ingest_row: IngestRow,
    chunk_size: int,
) -> None:
    """Read the stored file and process every row after the resume cursor, chunk by chunk."""
    report = _get_or_create_report(db, import_file.id)
    columns = mapped_columns(db, import_file.id)
    formats = import_formats(db, import_file)
    cursor = db.scalar(
        select(func.max(RawRow.row_number)).where(RawRow.import_file_id == import_file.id)
    )
    with open_import_records(import_file, storage, limits) as records:
        header = next(records, None)
        headers = [_header_text(cell) for cell in header[1]] if header else []
        run = _RunSettings(
            import_file=import_file,
            report=report,
            columns=columns,
            formats=formats,
            headers=headers,
            owners=build_owner_index(db),
            ingest_row=ingest_row,
            context=ImportContext(
                import_file_id=import_file.id,
                uploaded_by=import_file.uploaded_by,
                now=clock.now(),
                cooling_off_days=get_settings().cooling_off_days,
                source=IngestSource.IMPORT,
            ),
        )
        for chunk in _chunks(_after_cursor(records, cursor or 0), chunk_size):
            _process_chunk(db, run, chunk)
            db.commit()


def _after_cursor(records: Iterator[Record], cursor: int) -> Iterator[Record]:
    """Skip records already stored by an earlier run (row_number up to the cursor)."""
    return (record_ for record_ in records if record_[0] > cursor)


def _chunks(records: Iterator[Record], size: int) -> Iterator[list[Record]]:
    """Group records into lists of at most size, in order."""
    chunk: list[Record] = []
    for item in records:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _process_chunk(db: Session, run: _RunSettings, chunk: Sequence[Record]) -> None:
    """Store, ingest and count every row of the chunk; the caller commits once afterwards."""
    for row_number, cells in chunk:
        raw_row_id = _store_raw_row(db, run, row_number, cells)
        if raw_row_id is None:
            continue  # Already stored (cannot happen behind the cursor); never counted twice.
        mapped = apply_mapping(cells, run.columns, run.formats)
        source_row = SourceRow(
            row_number=row_number,
            values=mapped.values,
            raw_email=mapped.raw_email,
            import_file_id=run.import_file.id,
            source_profile_id=run.import_file.source_profile_id,
            default_country=run.import_file.default_country,
        )
        outcome = _ingest_isolated(db, run, source_row)
        # Link the lead and keep the result per row, so the report can list the rows that
        # failed or were quarantined with their reason (D-050). Neither column is guarded.
        db.execute(
            update(RawRow)
            .where(RawRow.id == raw_row_id)
            .values(
                person_id=outcome.person_id,
                outcome=outcome.kind,
                reason_code=_stored_reason(outcome),
            )
        )
        _count_outcome(run.report, outcome)


def _ingest_isolated(db: Session, run: _RunSettings, source_row: SourceRow) -> RowOutcome:
    """Call ingest_row for one row inside a SAVEPOINT; an error rejects only that row (D-068).

    The owner is set here too, so a failure while assigning rolls back the whole row. The
    broad except is deliberate: any bug in one row must not stop the other rows of the file.
    Only the row number and the exception type are logged, never lead data.
    """
    try:
        with db.begin_nested():
            outcome = run.ingest_row(db, source_row, run.context)
            owner_id = resolve_owner(run.owners, _owner_name(source_row))
            if owner_id is not None and outcome.person_id is not None:
                assign_owner_if_empty(db, outcome.person_id, owner_id)
    except Exception as error:  # noqa: BLE001 - per-row isolation, see docstring
        logger.warning(
            "import %s row %s rejected: ingest_row raised %s",
            run.import_file.id,
            source_row.row_number,
            type(error).__name__,
        )
        return RowOutcome(kind=RowOutcomeKind.REJECTED, reason_code=INGEST_ERROR_REASON)
    return outcome


def _stored_reason(outcome: RowOutcome) -> str | None:
    """The reason code kept on the raw row: only failures carry one, cut to the column length."""
    if outcome.kind not in _FAILURE_OUTCOMES:
        return None
    return (outcome.reason_code or UNSPECIFIED_REASON)[:REASON_CODE_MAX_LENGTH]


def _owner_name(source_row: SourceRow) -> str | None:
    """The row's source owner text, or None when the column is unmapped or empty."""
    value = source_row.values.get("owner_name")
    return value if isinstance(value, str) else None


def _count_outcome(report: ImportReport, outcome: RowOutcome) -> None:
    """Add one row to the report: received, the outcome counter and, for failures, the reason."""
    report.received += 1
    counter = _COUNTER_BY_OUTCOME[outcome.kind]
    setattr(report, counter, getattr(report, counter) + 1)
    if outcome.kind in _FAILURE_OUTCOMES:
        reason = outcome.reason_code or UNSPECIFIED_REASON
        # A new dict, because SQLAlchemy does not see an in-place change of a JSONB value.
        reasons = dict(report.failure_reasons) if isinstance(report.failure_reasons, dict) else {}
        reasons[reason] = reasons.get(reason, 0) + 1
        report.failure_reasons = reasons


# --- raw rows ---------------------------------------------------------------------------------


def _header_text(cell: object) -> str:
    """A header cell as trimmed text ('' when empty)."""
    return "" if cell is None else str(cell).strip()


def _json_cell(cell: object) -> object:
    """A cell as a JSON value, keeping text, numbers and booleans exactly as received."""
    if cell is None or isinstance(cell, str | int | float | bool):
        return cell
    if isinstance(cell, dt.datetime | dt.date | dt.time):
        return cell.isoformat()
    if isinstance(cell, Decimal):
        return str(cell)
    return str(cell)


def _original_values(headers: Sequence[str], cells: Sequence[object]) -> dict[str, object]:
    """The row keyed by header, or by column position where a header is empty or repeated."""
    # The key rule is shared with the owner assignment (imports.raw_keys), which reads it back.
    keys = original_value_keys(headers, len(cells))
    return {key: _json_cell(cell) for key, cell in zip(keys, cells, strict=True)}


def _normalized_email(columns: Sequence[MappedColumn], cells: Sequence[object]) -> str | None:
    """The mapped email cell, trimmed and lowercased, for raw_rows.email_normalized (D-099)."""
    for column in columns:
        if column.target_field == "email" and column.column_index < len(cells):
            cell = cells[column.column_index]
            if isinstance(cell, str) and cell.strip():
                return cell.strip().lower()[:EMAIL_NORMALIZED_MAX_LENGTH]
    return None


def _store_raw_row(
    db: Session, run: _RunSettings, row_number: int, cells: Sequence[object]
) -> uuid.UUID | None:
    """Insert the unmodified row (D-099); return its ID, or None if it already exists."""
    email = _normalized_email(run.columns, cells)
    statement = (
        insert(RawRow)
        .values(
            import_file_id=run.import_file.id,
            row_number=row_number,
            original_values=_original_values(run.headers, cells),
            email_normalized=email,
            created_at=clock.now(),
        )
        .on_conflict_do_nothing(constraint="uq_raw_rows_import_file_id_row_number")
        .returning(RawRow.id)
    )
    return db.scalar(statement)


# --- finishing --------------------------------------------------------------------------------


def _finish_import(db: Session, import_id: uuid.UUID) -> None:
    """Mark the import COMPLETED and audit it with the totals (no lead data)."""
    import_file = db.get(ImportFile, import_id)
    report = _get_or_create_report(db, import_id)
    assert import_file is not None  # run_import loaded it moments ago
    import_file.status = ImportStatus.COMPLETED
    record(
        db,
        action=AuditAction.IMPORT_FINISHED,
        actor_user_id=import_file.uploaded_by,
        object_type="import_file",
        object_id=str(import_id),
        summary={
            "received": report.received,
            "imported": report.imported,
            "updated": report.updated,
            "unchanged": report.unchanged,
            "duplicates_found": report.duplicates_found,
            "quarantined": report.quarantined,
            "rejected": report.rejected,
        },
    )
    db.commit()


def _fail_import(db: Session, import_id: uuid.UUID, reason: str) -> None:
    """Mark the import FAILED and audit a reason code only. Committed chunks are kept."""
    import_file = db.get(ImportFile, import_id)
    assert import_file is not None
    import_file.status = ImportStatus.FAILED
    record(
        db,
        action=AuditAction.IMPORT_FAILED,
        actor_user_id=import_file.uploaded_by,
        object_type="import_file",
        object_id=str(import_id),
        summary={"reason": reason},
    )
    db.commit()
    logger.error("import %s failed: %s", import_id, reason)


# --- progress ---------------------------------------------------------------------------------


def get_progress(
    db: Session, actor: User, import_id: uuid.UUID
) -> tuple[ImportFile, ImportReport | None]:
    """Return the import and its report so far (None before the import starts).

    Raises:
        ImportNotFoundError: If the import is missing or not visible to the actor.
    """
    import_file = get_import_for_viewer(db, actor, import_id)
    report = db.scalar(select(ImportReport).where(ImportReport.import_file_id == import_id))
    return import_file, report
