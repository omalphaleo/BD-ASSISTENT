"""Pydantic request and response models for the /imports endpoints.

Needed so the API boundary has typed, documented shapes (they become the generated frontend
client through openapi.json) and so responses never expose the storage key or server paths.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.imports.mapping import MappingView
from app.imports.models import ImportFile, ImportReport, ImportStatus
from app.imports.parsers import ParsedFile
from app.imports.upload import DuplicateFileInfo

# Upper bound for the columns of one mapping request (an XLSX sheet has at most 16,384).
MAX_MAPPING_COLUMNS = 16_384


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
    source_profile_id: uuid.UUID | None
    default_country: str | None
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


# --- Mapping, preview and estimate (M2-A2) ----------------------------------------------------


class TargetFieldResponse(BaseModel):
    """One canonical field a column can be mapped to (from the registry in leads.contracts)."""

    key: str
    group: str
    value_type: str
    label: str
    required: bool


class ProfileOptionResponse(BaseModel):
    """A source profile the uploader may choose (no saved mapping content is exposed)."""

    id: uuid.UUID
    name: str
    layout: str


class ChooseProfileRequest(BaseModel):
    """Body of PUT /imports/{id}/profile: the source profile and the default country (D-078)."""

    model_config = ConfigDict(extra="forbid")

    source_profile_id: uuid.UUID | None = None
    default_country: str | None = Field(default=None, max_length=128)


class MappingEntry(BaseModel):
    """One column's chosen target; null ignores the column (it stays in the raw rows)."""

    model_config = ConfigDict(extra="forbid")

    column_index: int = Field(ge=0)
    target_field: str | None = Field(default=None, max_length=128)


class SaveMappingRequest(BaseModel):
    """Body of PUT /imports/{id}/mapping; columns not listed are ignored."""

    model_config = ConfigDict(extra="forbid")

    columns: list[MappingEntry] = Field(max_length=MAX_MAPPING_COLUMNS)


class MappingColumnResponse(BaseModel):
    """One file column with its mapping; origin says where a suggestion came from."""

    column_index: int
    source_header: str
    target_field: str | None
    origin: str
    is_reassigned: bool


class ProfileSuggestionResponse(BaseModel):
    """A profile whose saved headers match the file; only a suggestion, the user confirms."""

    source_profile_id: uuid.UUID
    name: str
    overlap: float


class MappingResponse(BaseModel):
    """The mapping step: columns, whether they are saved, suggestions and what blocks start."""

    import_id: uuid.UUID
    is_saved: bool
    columns: list[MappingColumnResponse]
    profile_suggestions: list[ProfileSuggestionResponse]
    blocking_issues: list[str]

    @classmethod
    def from_view(cls, view: MappingView) -> "MappingResponse":
        """Build the response from the service's MappingView."""
        return cls(
            import_id=view.import_file.id,
            is_saved=view.is_saved,
            columns=[
                MappingColumnResponse(
                    column_index=c.column_index,
                    source_header=c.source_header,
                    target_field=c.target_field,
                    origin=c.origin.value,
                    is_reassigned=c.is_reassigned,
                )
                for c in view.columns
            ],
            profile_suggestions=[
                ProfileSuggestionResponse(
                    source_profile_id=s.profile_id, name=s.name, overlap=s.overlap
                )
                for s in view.profile_suggestions
            ],
            blocking_issues=list(view.blocking_issues),
        )


class SaveDefaultRequest(BaseModel):
    """Body of POST /imports/{id}/mapping/save-as-default (admins only)."""

    model_config = ConfigDict(extra="forbid")

    source_profile_id: uuid.UUID


class ProfileDefaultsResponse(BaseModel):
    """Result of saving a mapping as a profile's defaults."""

    source_profile_id: uuid.UUID
    columns_in_defaults: int


class CellWarningResponse(BaseModel):
    """A cell that could not be converted to its field's type; the value became null."""

    field: str
    code: str


class PreviewRowResponse(BaseModel):
    """One previewed row: its sheet position and the mapped values the pipeline would receive."""

    row_number: int
    values: dict[str, str | int | float | bool | None]
    warnings: list[CellWarningResponse]


class PreviewResponse(BaseModel):
    """The first rows of the file as the saved mapping reads them."""

    rows: list[PreviewRowResponse]


class UnmappedColumnResponse(BaseModel):
    """A file column that maps to no field (kept in the raw rows only)."""

    column_index: int
    source_header: str


class EstimateResponse(BaseModel):
    """What the file itself shows before the import starts (no match or duplicate numbers)."""

    rows_total: int
    rows_without_email: int
    rows_without_first_name: int
    warning_counts: dict[str, int]
    unmapped_columns: list[UnmappedColumnResponse]
    blocking_issues: list[str]
    can_start: bool


class MappingErrorResponse(BaseModel):
    """Body of a refused mapping step: a fixed message and a stable machine-readable code."""

    detail: str
    code: str


# --- Processing: start and progress (M2-A3) ---------------------------------------------------


class ImportProgressResponse(BaseModel):
    """How far an import is: status, rows handled so far and the outcome counters (D-050).

    Before the import starts every counter is 0. received counts rows already committed, so
    percent (received out of row_count) only moves forward, also after a worker restart.
    """

    status: ImportStatus
    row_count: int
    received: int
    imported: int
    updated: int
    unchanged: int
    duplicates_found: int
    quarantined: int
    rejected: int
    percent: int
    finished: bool

    @classmethod
    def from_models(
        cls, import_file: ImportFile, report: ImportReport | None
    ) -> "ImportProgressResponse":
        """Build the response from the import and its report (None before the first start)."""
        received = report.received if report else 0
        # An empty file has nothing to do, so a finished import always reads 100%.
        percent = (
            100
            if import_file.status is ImportStatus.COMPLETED
            else (min(100, received * 100 // import_file.row_count) if import_file.row_count else 0)
        )
        return cls(
            status=import_file.status,
            row_count=import_file.row_count,
            received=received,
            imported=report.imported if report else 0,
            updated=report.updated if report else 0,
            unchanged=report.unchanged if report else 0,
            duplicates_found=report.duplicates_found if report else 0,
            quarantined=report.quarantined if report else 0,
            rejected=report.rejected if report else 0,
            percent=percent,
            finished=import_file.status in (ImportStatus.COMPLETED, ImportStatus.FAILED),
        )
