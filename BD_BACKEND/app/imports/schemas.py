"""Pydantic request and response models for the /imports endpoints.

Needed so the API boundary has typed, documented shapes (they become the generated frontend
client through openapi.json) and so responses never expose the storage key or server paths.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.imports.models import ImportFile, ImportStatus
from app.imports.parsers import ParsedFile
from app.imports.upload import DuplicateFileInfo


class WorksheetResponse(BaseModel):
    """One worksheet of an XLSX upload; selectable sheets can be chosen for the import."""

    name: str
    row_count: int
    selectable: bool


class ImportFileResponse(BaseModel):
    """An import as shown in status calls (no storage key, no server path)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    status: ImportStatus
    worksheet: str | None
    row_count: int
    size_bytes: int | None
    uploaded_by: uuid.UUID | None
    created_at: datetime


class UploadResponse(ImportFileResponse):
    """The result of an upload: the import plus what the file contains.

    worksheets lists every sheet of an XLSX file (empty for CSV). When worksheet is null the
    file has several sheets and the user must pick one with POST /imports/{id}/worksheet.
    headers is set once a sheet is known (CSV, or a one-sheet XLSX), else null.
    """

    worksheets: list[WorksheetResponse]
    headers: list[str] | None

    @classmethod
    def from_outcome(cls, import_file: ImportFile, parsed: ParsedFile) -> "UploadResponse":
        """Combine the stored ImportFile with the parser's findings."""
        base = ImportFileResponse.model_validate(import_file)
        return cls(
            **base.model_dump(),
            worksheets=[
                WorksheetResponse(name=w.name, row_count=w.row_count, selectable=w.selectable)
                for w in parsed.worksheets
            ],
            headers=list(parsed.headers) if parsed.headers is not None else None,
        )


class SelectWorksheetRequest(BaseModel):
    """Body of POST /imports/{id}/worksheet."""

    model_config = ConfigDict(extra="forbid")

    worksheet: str = Field(min_length=1, max_length=255)


class UploadErrorResponse(BaseModel):
    """Body of a refused upload: a fixed message and a stable machine-readable code."""

    detail: str
    code: str


class DuplicateFileResponse(BaseModel):
    """Body of the 409 warning for a file that was already uploaded (D-109).

    The client shows the earlier date and user and offers "cancel" or "import anyway"; the
    latter means uploading the same file again with allow_duplicate=true.
    """

    detail: str
    code: str
    earlier_import_id: uuid.UUID
    earlier_uploaded_at: datetime
    earlier_uploaded_by: str | None

    @classmethod
    def from_info(cls, info: DuplicateFileInfo) -> "DuplicateFileResponse":
        """Build the warning body from the earlier upload's details."""
        return cls(
            detail="This file was already uploaded.",
            code="duplicate_file",
            earlier_import_id=info.import_file_id,
            earlier_uploaded_at=info.uploaded_at,
            earlier_uploaded_by=info.uploaded_by_email,
        )
