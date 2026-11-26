"""Receive an uploaded import file: duplicate check, validation, storage and the ImportFile row.

Needed because every import starts here (M2-A1). The service refuses a file whose SHA-256 was
uploaded before unless the user re-uploads with "import anyway" (D-109), validates it with the
parsers (D-110), keeps its bytes in the file storage and its metadata in PostgreSQL, and writes
the audit event. Lead deduplication is not done here: that belongs to the data-quality
workstream, and file hashes are deliberately not unique.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit.services import AuditAction, record
from app.core.models import User
from app.imports.access import can_change_import, can_view_import
from app.imports.errors import ImportNotFoundError, UploadErrorKind, UploadRejectedError
from app.imports.models import ImportFile, ImportStatus
from app.imports.parsers import (
    FileFormat,
    ParsedFile,
    UploadLimits,
    count_worksheet,
    detect_format,
    parse_upload,
)
from app.imports.storage import FileStorage, new_storage_key

AUDIT_OBJECT_TYPE = "import_file"
MAX_DISPLAY_NAME_LENGTH = 255
NOT_A_WORKBOOK_MESSAGE = "Only XLSX imports have worksheets."
NOT_EDITABLE_MESSAGE = "This import can no longer be changed."
SHEET_EMPTY_MESSAGE = "That worksheet has no data rows."
SHEET_TOO_LARGE_MESSAGE = "That worksheet has too many data rows."
# Statuses in which the worksheet may still be chosen (before mapping is finished).
EDITABLE_STATUSES = (ImportStatus.UPLOADED, ImportStatus.MAPPING)
_UNSAFE_NAME_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class DuplicateFileInfo:
    """The earlier upload of identical content that D-109 asks us to show."""

    import_file_id: uuid.UUID
    uploaded_at: datetime
    uploaded_by_email: str | None


class DuplicateFileError(Exception):
    """An identical file was uploaded before and the user did not choose "import anyway".

    Attributes:
        duplicate: Who uploaded it and when.
    """

    def __init__(self, duplicate: DuplicateFileInfo) -> None:
        super().__init__("duplicate file")
        self.duplicate = duplicate


@dataclass(frozen=True, slots=True)
class UploadOutcome:
    """A stored upload and what the parsers learned about it."""

    import_file: ImportFile
    parsed: ParsedFile


def clean_display_name(filename: str) -> str:
    """Make a client-supplied file name safe to store and show.

    The name is only ever a label: it never becomes part of a storage path. Directory parts
    and control characters are removed and the length is capped.
    """
    base = re.split(r"[\\/]", filename)[-1]
    cleaned = _UNSAFE_NAME_CHARACTERS.sub("", base).strip()
    return (cleaned or "upload")[:MAX_DISPLAY_NAME_LENGTH]


def find_earlier_upload(db: Session, sha256: str) -> DuplicateFileInfo | None:
    """Return the most recent earlier upload with this SHA-256, or None."""
    row = db.execute(
        select(ImportFile.id, ImportFile.created_at, User.email)
        .outerjoin(User, User.id == ImportFile.uploaded_by)
        .where(ImportFile.sha256 == sha256)
        .order_by(ImportFile.created_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    return DuplicateFileInfo(
        import_file_id=row.id, uploaded_at=row.created_at, uploaded_by_email=row.email
    )


def receive_upload(
    db: Session,
    actor: User,
    *,
    source: BinaryIO,
    size_bytes: int,
    sha256: str,
    filename: str,
    allow_duplicate: bool,
    storage: FileStorage,
    limits: UploadLimits,
    ip_address: str | None = None,
) -> UploadOutcome:
    """Check, store and register one uploaded file; commits on success.

    Order matters: the duplicate check and the validation both happen before the file is
    stored permanently, so a refused upload leaves nothing behind. The stored file and the
    database row succeed or fail together: if the commit fails the stored file is removed.

    Args:
        db: Session of the request.
        actor: The uploading user.
        source: Seekable binary file with the complete upload.
        size_bytes: Its size, already checked against the limit by the caller.
        sha256: Lowercase hex SHA-256 of the content.
        filename: The client's file name (display only).
        allow_duplicate: True when the user chose "import anyway" (D-109).
        storage: Where the bytes are kept.
        limits: Upload bounds.
        ip_address: Client address for the audit event.

    Raises:
        DuplicateFileError: If identical content was uploaded before and allow_duplicate is False.
        UploadRejectedError: If the type, structure or size of the file is not acceptable.
        StorageError: If the file cannot be stored.
    """
    file_format = detect_format(filename)
    duplicate = find_earlier_upload(db, sha256)
    if duplicate is not None and not allow_duplicate:
        raise DuplicateFileError(duplicate)

    parsed = parse_upload(source, file_format, limits)

    source.seek(0)
    storage_key = new_storage_key(file_format.value)
    storage.save(storage_key, source)
    try:
        import_file = ImportFile(
            sha256=sha256,
            filename=clean_display_name(filename),
            uploaded_by=actor.id,
            worksheet=parsed.selected_worksheet,
            status=ImportStatus.UPLOADED,
            row_count=parsed.row_count or 0,
            storage_key=storage_key,
            size_bytes=size_bytes,
        )
        db.add(import_file)
        db.flush()
        record(
            db,
            action=AuditAction.IMPORT_FILE_UPLOADED,
            actor_user_id=actor.id,
            object_type=AUDIT_OBJECT_TYPE,
            object_id=str(import_file.id),
            summary={
                "step": "uploaded",
                "file_format": file_format.value,
                "size_bytes": size_bytes,
                "row_count": parsed.row_count,
                "worksheet_count": len(parsed.worksheets),
            },
            ip_address=ip_address,
        )
        if duplicate is not None:
            # The user saw the warning and re-uploaded on purpose (D-109).
            record(
                db,
                action=AuditAction.IMPORT_DUPLICATE_FILE_OVERRIDDEN,
                actor_user_id=actor.id,
                object_type=AUDIT_OBJECT_TYPE,
                object_id=str(import_file.id),
                summary={"earlier_import_id": str(duplicate.import_file_id)},
                ip_address=ip_address,
            )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        storage.delete(storage_key)
        raise
    return UploadOutcome(import_file=import_file, parsed=parsed)


def get_import_for_viewer(db: Session, actor: User, import_id: uuid.UUID) -> ImportFile:
    """Load an import the actor may view.

    Raises:
        ImportNotFoundError: If it does not exist or the actor may not see it (same answer).
    """
    import_file = db.get(ImportFile, import_id)
    if import_file is None or not can_view_import(actor, import_file):
        raise ImportNotFoundError
    return import_file


def select_worksheet(
    db: Session,
    actor: User,
    import_id: uuid.UUID,
    worksheet_name: str,
    *,
    storage: FileStorage,
    limits: UploadLimits,
    ip_address: str | None = None,
) -> ImportFile:
    """Choose which worksheet of a stored XLSX import is imported (one sheet per import, D-110).

    The sheet is counted again from the stored file, so the row limit is checked on the sheet
    that is actually chosen. Commits on success.

    Raises:
        ImportNotFoundError: If the import is missing or not visible to the actor.
        UploadRejectedError: NOT_EDITABLE if the actor is not the uploader or the import has
            moved past mapping; BAD_WORKSHEET for a CSV import, an unknown sheet, or an
            empty or oversized sheet.
        StorageError: If the stored file cannot be read.
    """
    import_file = get_import_for_viewer(db, actor, import_id)
    if not can_change_import(actor, import_file) or import_file.status not in EDITABLE_STATUSES:
        raise UploadRejectedError(UploadErrorKind.NOT_EDITABLE, NOT_EDITABLE_MESSAGE)
    if import_file.storage_key is None or not import_file.storage_key.endswith(
        f".{FileFormat.XLSX.value}"
    ):
        raise UploadRejectedError(UploadErrorKind.BAD_WORKSHEET, NOT_A_WORKBOOK_MESSAGE)

    stored = storage.open(import_file.storage_key)
    try:
        info = count_worksheet(stored, worksheet_name, limits)
    finally:
        stored.close()
    if not info.selectable:
        message = SHEET_EMPTY_MESSAGE if info.row_count == 0 else SHEET_TOO_LARGE_MESSAGE
        raise UploadRejectedError(UploadErrorKind.BAD_WORKSHEET, message)

    import_file.worksheet = info.name
    import_file.row_count = info.row_count
    record(
        db,
        action=AuditAction.IMPORT_FILE_UPLOADED,
        actor_user_id=actor.id,
        object_type=AUDIT_OBJECT_TYPE,
        object_id=str(import_file.id),
        summary={"step": "worksheet_selected", "worksheet": info.name, "row_count": info.row_count},
        ip_address=ip_address,
    )
    db.commit()
    return import_file
