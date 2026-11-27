"""CSV downloads of an import's failed rows and of its change summary (M2-A5, D-050, D-111).

Needed so the importer, managers and admins can fix and re-upload the rows that did not become
leads, and keep a copy of what an import changed. Both files hold personal data, so each
download is audited (D-111) and every cell is neutralised against spreadsheet formula injection
(core.csv_safety: a cell starting with = + - @ tab or CR would otherwise run as a formula in
Excel). The routes in imports.reports_api call these functions; the files are built in memory
because an import is limited to 50,000 rows (D-110).
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.services import AuditAction, record
from app.core.csv_safety import csv_text
from app.core.models import User
from app.imports.models import ColumnMapping, RawRow
from app.imports.raw_keys import original_value_keys
from app.imports.reports import (
    changes_query,
    get_finished_import,
    get_report_for_finished_import,
    lead_change_views,
)
from app.leads.contracts import RowOutcomeKind

# The kinds of row that count as "failed" for the download (decided for M2-A5).
FAILED_OUTCOMES = (RowOutcomeKind.REJECTED, RowOutcomeKind.QUARANTINED)
FAILED_ROWS_HEADER = ("row_number", "outcome", "reason_code")
CHANGES_HEADER = ("lead", "email", "field", "old_value", "new_value")
# Values for the AuditAction.IMPORT_REPORT_DOWNLOADED summary: which file was downloaded.
FILE_FAILED_ROWS = "failed_rows"
FILE_CHANGES = "changes"


def _original_columns(db: Session, import_id: uuid.UUID, rows: Sequence[RawRow]) -> list[str]:
    """The original column keys in the file's order, then any key only the rows have.

    raw_rows.original_values is JSONB, which does not keep key order, so the order is rebuilt
    from the saved mapping (one entry per file column, by position) with the same key rule the
    pipeline used when it stored the row (imports.raw_keys). Keys the mapping cannot explain,
    for example a header that was reassigned in the wizard, follow in alphabetical order.
    """
    mappings = db.scalars(
        select(ColumnMapping)
        .where(ColumnMapping.import_file_id == import_id)
        .order_by(ColumnMapping.column_index)
    ).all()
    present = {key for row in rows for key in _values(row)}
    ordered: list[str] = []
    if mappings:
        headers = [""] * (mappings[-1].column_index + 1)
        for mapping in mappings:
            headers[mapping.column_index] = (mapping.source_header or "").strip()
        ordered = [key for key in original_value_keys(headers, len(headers)) if key in present]
    return ordered + sorted(present - set(ordered))


def _values(row: RawRow) -> dict[str, object]:
    """The row's original values as a dict (they are always an object; anything else is empty)."""
    return row.original_values if isinstance(row.original_values, dict) else {}


def build_failed_rows_csv(
    db: Session, actor: User, import_id: uuid.UUID, *, ip_address: str | None = None
) -> str:
    """Build the CSV of rejected and quarantined rows and audit the download (D-050, D-111).

    Columns: row number, outcome, reason code, then every original column exactly as uploaded,
    so the file can be corrected and uploaded again. Rows stored before the outcome was
    recorded (migration 0016) are not listed. The audit event records the file and the row
    count, never lead data.

    Raises:
        ImportNotFoundError: If the import does not exist or the actor may not see it.
        ReportRejectedError: NOT_FINISHED, while the import is not COMPLETED or FAILED.
    """
    import_file = get_finished_import(db, actor, import_id)
    rows = db.scalars(
        select(RawRow)
        .where(RawRow.import_file_id == import_file.id, RawRow.outcome.in_(FAILED_OUTCOMES))
        .order_by(RawRow.row_number)
    ).all()
    columns = _original_columns(db, import_file.id, rows)
    body = [
        [
            row.row_number,
            row.outcome.value if row.outcome else "",
            row.reason_code,
            *(_values(row).get(column) for column in columns),
        ]
        for row in rows
    ]
    _audit_download(db, actor, import_file.id, FILE_FAILED_ROWS, len(rows), ip_address)
    return csv_text([*FAILED_ROWS_HEADER, *columns], body)


def build_changes_csv(
    db: Session, actor: User, import_id: uuid.UUID, *, ip_address: str | None = None
) -> str:
    """Build the CSV of what the import changed (one line per changed field) and audit it.

    Raises:
        ImportNotFoundError: If the import does not exist or the actor may not see it.
        ReportRejectedError: NOT_FINISHED, while the import is not COMPLETED or FAILED.
    """
    import_file = get_finished_import(db, actor, import_id)
    report = get_report_for_finished_import(db, import_file)
    views = lead_change_views(db, db.execute(changes_query(report.id)).all())
    body = [
        [view.name, view.email, change.label, change.old, change.new]
        for view in views
        for change in view.changes
    ]
    _audit_download(db, actor, import_file.id, FILE_CHANGES, len(body), ip_address)
    return csv_text(CHANGES_HEADER, body)


def _audit_download(
    db: Session,
    actor: User,
    import_id: uuid.UUID,
    file: str,
    row_count: int,
    ip_address: str | None,
) -> None:
    """Record who downloaded which file of which import (D-111) and commit the event."""
    record(
        db,
        action=AuditAction.IMPORT_REPORT_DOWNLOADED,
        actor_user_id=actor.id,
        object_type="import_file",
        object_id=str(import_id),
        summary={"file": file, "row_count": row_count},
        ip_address=ip_address,
    )
    db.commit()
