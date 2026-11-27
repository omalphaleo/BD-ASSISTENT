"""Quarantine service: hold, list, fix, release and discard import rows that failed validation.

Needed because a bad row must never fail a whole file (D-068): valid rows import, problem rows
wait here until BD fixes and releases them or discards them (D-107). The import pipeline's
ingest_row (M2-B4) calls quarantine_row() to park a row; the /quarantine endpoints call the
other functions. Release goes back through the same ingest_row an import uses, so a fixed row
is treated exactly like a new one. Every state change writes an audit event that names fields
and reason codes only, never lead values, because the audit log is permanent.
"""

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.audit.services import AuditAction, record
from app.core.clock import now
from app.core.models import User, UserRole
from app.core.permissions import Permission, PermissionDeniedError, has_permission
from app.imports.models import ImportFile, RawRow
from app.leads.contracts import (
    ImportContext,
    IngestRow,
    IngestSource,
    JsonScalar,
    RowOutcomeKind,
    SourceRow,
)
from app.leads.engagement import read_cooling_off_days
from app.leads.models import QuarantineRecord, QuarantineStatus
from app.leads.validation import RowIssue, ValidationResult, validate_row

# Payload keys (the mapped app field names a quarantined row carries). ASSUMPTION until the
# column-mapping task (M2-A2) fixes the app field names: these are the names B1's validation
# reads. The first email is the primary one; the others are secondary and tertiary (D-072).
FIRST_NAME_FIELD = "first_name"
EMAIL_FIELDS = ("email", "secondary_email", "tertiary_email")
EMAIL_STATUS_FIELD = "email_status"

# Outcomes of ingest_row that mean the row is now a lead (a possible duplicate is still
# imported, as a separate record, D-092), so the quarantine record is resolved.
_RELEASED_OUTCOMES = frozenset(
    {
        RowOutcomeKind.IMPORTED,
        RowOutcomeKind.UPDATED,
        RowOutcomeKind.UNCHANGED,
        RowOutcomeKind.POSSIBLE_DUPLICATE,
    }
)

# Field names BD may edit: lowercase snake case, so a typo or a hostile key cannot be stored.
_FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MAX_PAYLOAD_FIELDS = 100
MAX_VALUE_LENGTH = 2000

AUDIT_OBJECT_TYPE = "quarantine_record"


class QuarantineNotFoundError(Exception):
    """The quarantine record does not exist."""


class QuarantineNotOpenError(Exception):
    """The record was already released or discarded, so it can no longer change."""


class QuarantineNotReleasableError(Exception):
    """The record has no linked raw row or import file, so it cannot be re-ingested."""


class QuarantineFieldError(ValueError):
    """An edited field name or value is not acceptable (bad name, too long, too many)."""


class IngestUnavailableError(Exception):
    """ingest_row is not available yet (M2-B4), so a valid row cannot be released."""


@dataclass(frozen=True, slots=True)
class QuarantineItem:
    """A quarantine record together with where its row came from.

    Attributes:
        record: The QuarantineRecord itself.
        import_file_id: The file the row came from, or None when no raw row is linked.
        filename: That file's display name.
        row_number: One-based row number in the sheet.
        uploaded_by: The importer, or None when unknown (uploader deleted or no raw row).
    """

    record: QuarantineRecord
    import_file_id: uuid.UUID | None
    filename: str | None
    row_number: int | None
    uploaded_by: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class ReleaseResult:
    """What happened when a user tried to release a record.

    Attributes:
        released: True when the row became a lead and the record is resolved.
        item: The record after the attempt (still open when released is False).
        outcome: What ingest_row did, or None when validation failed before ingest.
    """

    released: bool
    item: QuarantineItem
    outcome: RowOutcomeKind | None


def _as_text(value: JsonScalar) -> str | None:
    """Convert a payload value to text for validation (numbers and booleans become text)."""
    return None if value is None else str(value)


def validate_payload(payload: Mapping[str, JsonScalar]) -> ValidationResult:
    """Run B1's row validation on a quarantine payload."""
    return validate_row(
        first_name=_as_text(payload.get(FIRST_NAME_FIELD)),
        emails=[_as_text(payload.get(field)) for field in EMAIL_FIELDS],
        work_email_status=_as_text(payload.get(EMAIL_STATUS_FIELD)),
    )


def _payload_of(quarantine_record: QuarantineRecord) -> dict[str, JsonScalar]:
    """Return the record's payload as a plain dict (empty if it is not an object)."""
    payload = quarantine_record.payload
    return dict(payload) if isinstance(payload, Mapping) else {}


def quarantine_row(db: Session, row: SourceRow, issues: Sequence[RowIssue]) -> QuarantineRecord:
    """Park an invalid import row (called by ingest_row); never commits.

    Idempotent per raw row: if the row already has a record (the job is re-run after a worker
    crash, or a release failed validation again) the record is refreshed instead of duplicated,
    because raw_row_id is unique. A record that was already released or discarded is left as
    it is.

    Args:
        db: The caller's session; the caller owns the transaction.
        row: The mapped row; its values become the editable payload.
        issues: Why the row failed; must not be empty.

    Raises:
        ValueError: If issues is empty (a valid row must not be quarantined).
    """
    if not issues:
        raise ValueError("a row without issues must not be quarantined")
    payload: dict[str, JsonScalar] = dict(row.values)
    # Keep the email text exactly as received so BD sees what the file contained.
    if row.raw_email is not None and not payload.get(EMAIL_FIELDS[0]):
        payload[EMAIL_FIELDS[0]] = row.raw_email

    raw_row_id = db.scalar(
        select(RawRow.id).where(
            RawRow.import_file_id == row.import_file_id, RawRow.row_number == row.row_number
        )
    )
    existing = (
        db.scalar(select(QuarantineRecord).where(QuarantineRecord.raw_row_id == raw_row_id))
        if raw_row_id is not None
        else None
    )
    issue_codes = [issue.value for issue in issues]
    if existing is not None:
        if existing.status == QuarantineStatus.OPEN:
            existing.issues = issue_codes
            existing.payload = payload
            db.flush()
        return existing

    created = QuarantineRecord(
        issues=issue_codes, status=QuarantineStatus.OPEN, payload=payload, raw_row_id=raw_row_id
    )
    db.add(created)
    db.flush()
    return created


def _item_query() -> Select[tuple[QuarantineRecord, RawRow | None, ImportFile | None]]:
    """Select a record with its raw row and import file (both may be missing)."""
    return (
        select(QuarantineRecord, RawRow, ImportFile)
        .outerjoin(RawRow, RawRow.id == QuarantineRecord.raw_row_id)
        .outerjoin(ImportFile, ImportFile.id == RawRow.import_file_id)
    )


def _to_item(
    quarantine_record: QuarantineRecord, raw_row: RawRow | None, import_file: ImportFile | None
) -> QuarantineItem:
    """Combine one joined result row into a QuarantineItem."""
    return QuarantineItem(
        record=quarantine_record,
        import_file_id=import_file.id if import_file else None,
        filename=import_file.filename if import_file else None,
        row_number=raw_row.row_number if raw_row else None,
        uploaded_by=import_file.uploaded_by if import_file else None,
    )


def list_items(
    db: Session,
    *,
    status: QuarantineStatus | None = QuarantineStatus.OPEN,
    issue: RowIssue | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[QuarantineItem], int]:
    """List quarantine records, newest first, with the total number matching the filters.

    Any BD user may list every record (D-107: any BD user can fix and release a row).

    Args:
        status: Only this status; None lists every status.
        issue: Only records that carry this reason code.
        limit: Page size.
        offset: Records to skip.

    Returns:
        The page of items and the total count before paging.
    """
    filters = []
    if status is not None:
        filters.append(QuarantineRecord.status == status)
    if issue is not None:
        filters.append(QuarantineRecord.issues.contains([issue.value]))
    total = db.scalar(select(func.count()).select_from(QuarantineRecord).where(*filters)) or 0
    rows = db.execute(
        _item_query()
        .where(*filters)
        # id breaks ties so paging stays stable when rows share a creation time.
        .order_by(QuarantineRecord.created_at.desc(), QuarantineRecord.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [_to_item(*row) for row in rows], total


def _load(db: Session, record_id: uuid.UUID, *, lock: bool = False) -> QuarantineItem:
    """Load one item; with lock=True the record row is locked until the transaction ends.

    The lock stops two people releasing or discarding the same record at once.

    Raises:
        QuarantineNotFoundError: If no record has this id.
    """
    query = _item_query().where(QuarantineRecord.id == record_id)
    if lock:
        # "of" locks only the record: PostgreSQL cannot lock the nullable side of an outer join.
        query = query.with_for_update(of=QuarantineRecord)
    row = db.execute(query).one_or_none()
    if row is None:
        raise QuarantineNotFoundError
    return _to_item(*row)


def get_item(db: Session, record_id: uuid.UUID) -> QuarantineItem:
    """Return one record with its source row.

    Raises:
        QuarantineNotFoundError: If no record has this id.
    """
    return _load(db, record_id)


def _require_permission(actor: User, permission: Permission) -> None:
    """Re-check the role capability in the service (the route guard is not enough alone).

    Raises:
        PermissionDeniedError: If the actor's role does not grant the capability.
    """
    if not has_permission(actor, permission):
        raise PermissionDeniedError


def _require_open(item: QuarantineItem) -> None:
    """Raise unless the record is still open.

    Raises:
        QuarantineNotOpenError: If it was already released or discarded.
    """
    if item.record.status != QuarantineStatus.OPEN:
        raise QuarantineNotOpenError


def _clean_changes(changes: Mapping[str, JsonScalar]) -> dict[str, JsonScalar]:
    """Validate edited fields; blank text becomes None so a value can be cleared.

    Raises:
        QuarantineFieldError: If a name is not lowercase snake case, a text value is too
            long, or more than MAX_PAYLOAD_FIELDS fields are sent.
    """
    if len(changes) > MAX_PAYLOAD_FIELDS:
        raise QuarantineFieldError("too many fields")
    cleaned: dict[str, JsonScalar] = {}
    for name, value in changes.items():
        if not _FIELD_NAME.match(name):
            raise QuarantineFieldError(f"invalid field name: {name!r}")
        if isinstance(value, str):
            value = value.strip() or None
            if value is not None and len(value) > MAX_VALUE_LENGTH:
                raise QuarantineFieldError(f"value too long for field {name!r}")
        cleaned[name] = value
    return cleaned


def fix_item(
    db: Session,
    actor: User,
    record_id: uuid.UUID,
    changes: Mapping[str, JsonScalar],
    *,
    ip_address: str | None = None,
) -> QuarantineItem:
    """Edit the payload of an open record (for example add a work email) and revalidate it.

    Any BD user may do this (D-107). The original row in raw_rows is never touched (D-099).
    The record stays open; its reason codes are refreshed so BD sees what is still wrong, and
    an empty list means it is ready to release.

    Raises:
        PermissionDeniedError: If the actor may not fix quarantine records.
        QuarantineNotFoundError: If the record does not exist.
        QuarantineNotOpenError: If it was already released or discarded.
        QuarantineFieldError: If a field name or value is not acceptable.
    """
    _require_permission(actor, Permission.FIX_QUARANTINE)
    cleaned = _clean_changes(changes)
    item = _load(db, record_id, lock=True)
    _require_open(item)

    target = item.record
    issues_before = list(target.issues)
    # Reassign a new dict: JSONB columns do not notice in-place changes.
    target.payload = {**_payload_of(target), **cleaned}
    target.issues = [issue.value for issue in validate_payload(_payload_of(target)).issues]
    record(
        db,
        action=AuditAction.QUARANTINE_FIXED,
        actor_user_id=actor.id,
        object_type=AUDIT_OBJECT_TYPE,
        object_id=str(target.id),
        # Field names and reason codes only: the log is permanent and must hold no lead data.
        summary={
            "fields_changed": sorted(cleaned),
            "issues_before": issues_before,
            "issues_after": list(target.issues),
        },
        ip_address=ip_address,
    )
    db.commit()
    return item


def release_item(
    db: Session,
    actor: User,
    record_id: uuid.UUID,
    ingest_row: IngestRow,
    *,
    ip_address: str | None = None,
) -> ReleaseResult:
    """Revalidate an open record and, if it is valid, send it through ingest_row.

    Any BD user may release (D-107). Validation runs first: a record that still has issues
    stays open with refreshed reason codes and ingest_row is not called. A valid record goes
    through the same ingest_row an import uses (ImportContext.source is QUARANTINE_RELEASE);
    if that imports, updates or flags the row as a possible duplicate, the record is resolved
    and the raw row is linked to the lead. Any other outcome leaves the record open.

    Args:
        ingest_row: W2's row pipeline (M2-B4). Raises IngestUnavailableError until it exists.

    Raises:
        PermissionDeniedError: If the actor may not release quarantine records.
        QuarantineNotFoundError: If the record does not exist.
        QuarantineNotOpenError: If it was already released or discarded.
        QuarantineNotReleasableError: If the record has no linked raw row or import file.
        IngestUnavailableError: If the row is valid but ingest_row is not available yet.
    """
    _require_permission(actor, Permission.FIX_QUARANTINE)
    item = _load(db, record_id, lock=True)
    _require_open(item)
    target = item.record
    raw_row = db.get(RawRow, target.raw_row_id) if target.raw_row_id else None
    import_file = db.get(ImportFile, raw_row.import_file_id) if raw_row else None
    if raw_row is None or import_file is None:
        raise QuarantineNotReleasableError

    payload = _payload_of(target)
    validation = validate_payload(payload)
    if not validation.is_valid:
        target.issues = [issue.value for issue in validation.issues]
        db.commit()
        return ReleaseResult(released=False, item=item, outcome=None)

    source_row = SourceRow(
        row_number=raw_row.row_number,
        values=payload,
        raw_email=_as_text(payload.get(EMAIL_FIELDS[0])),
        import_file_id=import_file.id,
        source_profile_id=import_file.source_profile_id,
        default_country=import_file.default_country,
    )
    context = ImportContext(
        import_file_id=import_file.id,
        uploaded_by=import_file.uploaded_by,
        now=now(),
        cooling_off_days=read_cooling_off_days(db),
        source=IngestSource.QUARANTINE_RELEASE,
    )
    outcome = ingest_row(db, source_row, context)

    if outcome.kind not in _RELEASED_OUTCOMES:
        # ingest_row still refuses the row (for example a rule only it knows): keep it open.
        if outcome.reason_code:
            target.issues = [outcome.reason_code]
        db.commit()
        return ReleaseResult(released=False, item=item, outcome=outcome.kind)

    target.status = QuarantineStatus.RELEASED
    target.resolved_by = actor.id
    target.resolved_at = now()
    if outcome.person_id is not None:
        # person_id is the one raw_rows column the immutability trigger allows to change.
        raw_row.person_id = outcome.person_id
    record(
        db,
        action=AuditAction.QUARANTINE_RELEASED,
        actor_user_id=actor.id,
        object_type=AUDIT_OBJECT_TYPE,
        object_id=str(target.id),
        summary={"outcome": outcome.kind.value},
        ip_address=ip_address,
    )
    db.commit()
    return ReleaseResult(released=True, item=item, outcome=outcome.kind)


def can_discard(actor: User, importer_id: uuid.UUID | None) -> bool:
    """Only the importer, a manager or an admin may discard (D-107).

    Args:
        importer_id: The user who uploaded the file; None when unknown, in which case only
            a manager or an admin may discard.
    """
    if actor.role in (UserRole.MANAGER, UserRole.ADMIN):
        return True
    return importer_id is not None and importer_id == actor.id


def discard_item(
    db: Session, actor: User, record_id: uuid.UUID, *, ip_address: str | None = None
) -> QuarantineItem:
    """Discard an open record; the row never becomes a lead. Audited (D-107).

    The raw row stays in raw_rows (D-099); only erase-person removes it.

    Raises:
        PermissionDeniedError: If the actor is neither the importer, a manager nor an admin.
        QuarantineNotFoundError: If the record does not exist.
        QuarantineNotOpenError: If it was already released or discarded.
    """
    _require_permission(actor, Permission.DISCARD_QUARANTINE)
    item = _load(db, record_id, lock=True)
    if not can_discard(actor, item.uploaded_by):
        raise PermissionDeniedError
    _require_open(item)

    target = item.record
    target.status = QuarantineStatus.DISCARDED
    target.resolved_by = actor.id
    target.resolved_at = now()
    record(
        db,
        action=AuditAction.QUARANTINE_DISCARDED,
        actor_user_id=actor.id,
        object_type=AUDIT_OBJECT_TYPE,
        object_id=str(target.id),
        summary={"issues": list(target.issues)},
        ip_address=ip_address,
    )
    db.commit()
    return item
