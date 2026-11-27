"""Preview the first rows of an import and estimate it before anything is saved.

Needed so the uploader can check that the chosen mapping reads the file correctly before
starting the import (m2.md task M2-A2). The preview shows the first rows exactly as they would
be handed to the pipeline (mapped values, plus cells that could not be converted); the
estimate scans the whole file once and counts only what the file itself shows. It says nothing
about matches, duplicates or quarantine: those depend on data-quality rules that belong to W2
(and the match confidence scoring is still unresolved), so they cannot be promised here.
Nothing is written to the database.
"""

import uuid
from dataclasses import dataclass
from itertools import islice

from sqlalchemy.orm import Session

from app.core.models import User
from app.imports.mapping import (
    CellWarning,
    MappedRow,
    apply_mapping,
    blocking_issues,
    get_mapping_view,
    import_formats,
    mapped_columns,
    open_import_records,
)
from app.imports.parsers import UploadLimits
from app.imports.storage import FileStorage
from app.imports.upload import get_import_for_viewer

PREVIEW_ROWS = 10


@dataclass(frozen=True, slots=True)
class PreviewRow:
    """One previewed row: its sheet position and what the mapping reads from it."""

    row_number: int
    values: dict[str, str | int | float | bool | None]
    warnings: tuple[CellWarning, ...]


@dataclass(frozen=True, slots=True)
class UnmappedColumn:
    """A file column that maps to no field; it is kept in raw_rows only."""

    column_index: int
    source_header: str


@dataclass(frozen=True, slots=True)
class Estimate:
    """What a full scan of the file shows before the import starts.

    Attributes:
        rows_total: Non-empty data rows below the header.
        rows_without_email: Rows whose email cell is blank (D-069 makes the email mandatory).
        rows_without_first_name: Rows whose first-name cell is blank (D-069).
        warning_counts: Field key -> number of cells that could not be converted.
        unmapped_columns: Columns that map to no field.
        blocking_issues: Mandatory fields no column fills; "start import" stays disabled.
    """

    rows_total: int
    rows_without_email: int
    rows_without_first_name: int
    warning_counts: dict[str, int]
    unmapped_columns: tuple[UnmappedColumn, ...]
    blocking_issues: tuple[str, ...]

    @property
    def can_start(self) -> bool:
        """True when every mandatory field is mapped and the file has data rows."""
        return not self.blocking_issues and self.rows_total > 0


def build_preview(
    db: Session,
    actor: User,
    import_id: uuid.UUID,
    *,
    storage: FileStorage,
    limits: UploadLimits,
    sample_size: int = PREVIEW_ROWS,
) -> list[PreviewRow]:
    """Map the first data rows of the file with the saved mapping.

    Raises:
        ImportNotFoundError: If the import is missing or not visible to the actor.
        MappingRejectedError: MAPPING_NOT_SAVED if no mapping was saved yet.
        UploadRejectedError: If the stored file is no longer readable.
    """
    import_file = get_import_for_viewer(db, actor, import_id)
    columns = mapped_columns(db, import_id)
    formats = import_formats(db, import_file)
    with open_import_records(import_file, storage, limits) as records:
        next(records, None)  # the header row
        data_rows = list(islice(records, sample_size))
    previews: list[PreviewRow] = []
    for row_number, cells in data_rows:
        mapped = apply_mapping(cells, columns, formats)
        previews.append(PreviewRow(row_number, mapped.values, mapped.warnings))
    return previews


def _blank(mapped: MappedRow, field: str) -> bool:
    """True when the mapped row has no value for the field (also when it is not mapped)."""
    return mapped.values.get(field) is None


def build_estimate(
    db: Session,
    actor: User,
    import_id: uuid.UUID,
    *,
    storage: FileStorage,
    limits: UploadLimits,
) -> Estimate:
    """Scan the whole file once with the saved mapping and count what it shows.

    Raises:
        ImportNotFoundError: If the import is missing or not visible to the actor.
        MappingRejectedError: MAPPING_NOT_SAVED if no mapping was saved yet.
        UploadRejectedError: If the stored file is no longer readable.
    """
    import_file = get_import_for_viewer(db, actor, import_id)
    columns = mapped_columns(db, import_id)  # raises MAPPING_NOT_SAVED before the file is read
    view = get_mapping_view(db, actor, import_id, storage=storage, limits=limits)
    formats = import_formats(db, import_file)

    rows_total = without_email = without_first_name = 0
    warning_counts: dict[str, int] = {}
    with open_import_records(import_file, storage, limits) as records:
        next(records, None)  # the header row
        for _, cells in records:
            mapped = apply_mapping(cells, columns, formats)
            rows_total += 1
            without_email += _blank(mapped, "email")
            without_first_name += _blank(mapped, "first_name")
            for warning in mapped.warnings:
                warning_counts[warning.field] = warning_counts.get(warning.field, 0) + 1
    return Estimate(
        rows_total=rows_total,
        rows_without_email=without_email,
        rows_without_first_name=without_first_name,
        warning_counts=warning_counts,
        unmapped_columns=tuple(
            UnmappedColumn(c.column_index, c.source_header)
            for c in view.columns
            if c.target_field is None
        ),
        blocking_issues=blocking_issues(view.columns),
    )
