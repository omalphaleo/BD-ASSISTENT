"""Map a file's columns to the canonical lead fields: suggest, validate, save and apply.

Needed so any source (Apollo, another provider, a hand-made spreadsheet) can be imported
through one engine: the server suggests which column means what, the uploader corrects it
(including headers that are missing or wrong, D-049), the result is saved per file in
column_mappings, and an admin may save it as the profile's default for the next file. Columns
are matched by header text, never by position (D-040), and columns that map to nothing stay in
raw_rows only (Q-IMPORT-11). The M2-A3 pipeline reuses apply_mapping(). Nothing here
validates, matches or merges leads: that is W2's job behind ingest_row.
"""

import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit.services import AuditAction, record
from app.core.models import User
from app.imports.access import can_change_import
from app.imports.conversion import DEFAULT_FORMAT, FieldFormat, convert_cell, is_blank
from app.imports.errors import MappingErrorKind, MappingRejectedError
from app.imports.layouts import BUILTIN_ALIAS_LOOKUP, normalize_header
from app.imports.models import ColumnMapping, ImportFile, ImportStatus, SourceProfile
from app.imports.parsers import FileFormat, UploadLimits, iter_records
from app.imports.storage import FileStorage
from app.imports.upload import EDITABLE_STATUSES, get_import_for_viewer
from app.leads.contracts import REQUIRED_FIELD_KEYS, TARGET_FIELDS_BY_KEY, JsonScalar

AUDIT_OBJECT_TYPE = "import_file"
PROFILE_AUDIT_OBJECT_TYPE = "source_profile"
# A profile is suggested when at least this share of the file's non-empty headers is known to
# it. The user always confirms the suggestion; it is never applied automatically.
MIN_PROFILE_OVERLAP = 0.5

NOT_EDITABLE_MESSAGE = "This import can no longer be changed."
WORKSHEET_REQUIRED_MESSAGE = "Choose a worksheet before mapping columns."
FILE_NOT_READABLE_MESSAGE = "The stored file could not be read."
UNKNOWN_PROFILE_MESSAGE = "That source profile does not exist or is not active."
INVALID_PROFILE_MESSAGE = "The saved mapping of this source profile is invalid. Ask an admin."
MAPPING_NOT_SAVED_MESSAGE = "Save the column mapping first."


class MappingOrigin(StrEnum):
    """Where a column's target came from, so the screen can explain a suggestion."""

    SAVED = "saved"  # the mapping already stored for this file
    PROFILE = "profile"  # the chosen source profile's saved defaults
    BUILTIN = "builtin"  # the built-in Apollo / common-header aliases
    UNMAPPED = "unmapped"  # nothing matched (or the user left it unmapped)


class MappingDefaults(BaseModel):
    """The shape of SourceProfile.mapping_defaults (version 1).

    Attributes:
        columns: Normalized header text -> target field key.
        formats: Target field key -> parsing hints (decimal separator, date format).
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    columns: dict[str, str] = Field(default_factory=dict)
    formats: dict[str, FieldFormat] = Field(default_factory=dict)

    @field_validator("columns")
    @classmethod
    def _targets_exist(cls, columns: dict[str, str]) -> dict[str, str]:
        """Every saved target must be a registry key, or W2 would receive an unknown field."""
        unknown = sorted(set(columns.values()) - TARGET_FIELDS_BY_KEY.keys())
        if unknown:
            raise ValueError(f"unknown target fields: {unknown}")
        return columns

    @field_validator("formats")
    @classmethod
    def _format_keys_exist(cls, formats: dict[str, FieldFormat]) -> dict[str, FieldFormat]:
        """Formats may only be declared for registry keys."""
        unknown = sorted(set(formats) - TARGET_FIELDS_BY_KEY.keys())
        if unknown:
            raise ValueError(f"unknown target fields: {unknown}")
        return formats


@dataclass(frozen=True, slots=True)
class MappingColumn:
    """One file column and what it is mapped to (None: ignored, kept in raw_rows only)."""

    column_index: int
    source_header: str
    target_field: str | None
    origin: MappingOrigin
    is_reassigned: bool = False


@dataclass(frozen=True, slots=True)
class ProfileSuggestion:
    """A source profile whose saved headers overlap the file's headers."""

    profile_id: uuid.UUID
    name: str
    overlap: float


@dataclass(frozen=True, slots=True)
class MappingView:
    """Everything the mapping step shows: columns, whether they are saved, and what blocks."""

    import_file: ImportFile
    columns: tuple[MappingColumn, ...]
    is_saved: bool
    profile_suggestions: tuple[ProfileSuggestion, ...]
    blocking_issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MappedColumn:
    """A mapped column as the row mapper needs it: where to read and which field to fill."""

    column_index: int
    target_field: str


@dataclass(frozen=True, slots=True)
class CellWarning:
    """A cell that could not be converted to its field's type (the value became None)."""

    field: str
    code: str


@dataclass(frozen=True, slots=True)
class MappedRow:
    """One file row after mapping: the SourceRow values, the raw email text and warnings."""

    values: dict[str, JsonScalar]
    raw_email: str | None
    warnings: tuple[CellWarning, ...]


# --- reading the stored file ------------------------------------------------------------------


@contextmanager
def open_import_records(
    import_file: ImportFile, storage: FileStorage, limits: UploadLimits
) -> Iterator[Iterator[tuple[int, list[object]]]]:
    """Open the stored file and yield its (row_number, cells) records, header first.

    Raises:
        MappingRejectedError: FILE_NOT_READABLE if the import has no stored file;
            WORKSHEET_REQUIRED for a multi-sheet XLSX with no chosen sheet.
        UploadRejectedError: If the stored file is no longer readable.
        StorageError: If the storage cannot open the file.
    """
    key = import_file.storage_key
    if key is None:
        raise MappingRejectedError(MappingErrorKind.FILE_NOT_READABLE, FILE_NOT_READABLE_MESSAGE)
    file_format = FileFormat.XLSX if key.endswith(f".{FileFormat.XLSX.value}") else FileFormat.CSV
    if file_format is FileFormat.XLSX and import_file.worksheet is None:
        raise MappingRejectedError(MappingErrorKind.WORKSHEET_REQUIRED, WORKSHEET_REQUIRED_MESSAGE)
    stored = storage.open(key)
    try:
        with closing(iter_records(stored, file_format, import_file.worksheet, limits)) as records:
            yield records
    finally:
        stored.close()


def _header_text(cell: object) -> str:
    """A header cell as trimmed text; an empty cell is ''."""
    return "" if cell is None else str(cell).strip()


def read_headers(
    import_file: ImportFile, storage: FileStorage, limits: UploadLimits
) -> tuple[str, ...]:
    """Return the header row of the stored file (empty cells as '', D-049).

    Raises:
        MappingRejectedError: FILE_NOT_READABLE if the file has no header row.
    """
    with open_import_records(import_file, storage, limits) as records:
        first = next(records, None)
    if first is None:
        raise MappingRejectedError(MappingErrorKind.FILE_NOT_READABLE, FILE_NOT_READABLE_MESSAGE)
    return tuple(_header_text(cell) for cell in first[1])


# --- profiles and suggestions -----------------------------------------------------------------


def load_defaults(profile: SourceProfile | None) -> MappingDefaults:
    """Parse a profile's mapping_defaults; no profile gives empty defaults.

    Raises:
        MappingRejectedError: INVALID_PROFILE if the stored JSON does not match the version-1
            shape (a hand-edited or outdated profile must be fixed, not silently ignored).
    """
    if profile is None:
        return MappingDefaults()
    try:
        return MappingDefaults.model_validate(profile.mapping_defaults)
    except ValidationError as exc:
        raise MappingRejectedError(
            MappingErrorKind.INVALID_PROFILE, INVALID_PROFILE_MESSAGE
        ) from exc


def _profile_of(db: Session, import_file: ImportFile) -> SourceProfile | None:
    """The source profile chosen for this import, if any."""
    if import_file.source_profile_id is None:
        return None
    return db.get(SourceProfile, import_file.source_profile_id)


def _suggest_target(header: str, defaults: MappingDefaults) -> tuple[str | None, MappingOrigin]:
    """Target for one header: the profile's saved default first, then the built-in aliases."""
    normalized = normalize_header(header)
    if not normalized:
        return None, MappingOrigin.UNMAPPED  # a missing header must be assigned by the user
    if normalized in defaults.columns:
        return defaults.columns[normalized], MappingOrigin.PROFILE
    if normalized in BUILTIN_ALIAS_LOOKUP:
        return BUILTIN_ALIAS_LOOKUP[normalized], MappingOrigin.BUILTIN
    return None, MappingOrigin.UNMAPPED


def suggest_columns(headers: Sequence[str], defaults: MappingDefaults) -> list[MappingColumn]:
    """Suggest a target for every column. One target is given to one column only.

    When two columns would get the same target the first one keeps it and the later one is
    left unmapped, so the user decides which column wins instead of the server guessing.
    """
    claimed: set[str] = set()
    columns: list[MappingColumn] = []
    for index, header in enumerate(headers):
        target, origin = _suggest_target(header, defaults)
        if target is not None and target in claimed:
            target, origin = None, MappingOrigin.UNMAPPED
        if target is not None:
            claimed.add(target)
        columns.append(MappingColumn(index, header, target, origin))
    return columns


def suggest_profiles(
    headers: Sequence[str], profiles: Sequence[SourceProfile]
) -> list[ProfileSuggestion]:
    """Rank the active profiles whose saved headers cover enough of the file's headers.

    Overlap is (file headers known to the profile) / (non-empty file headers), compared on
    normalized text. Only a suggestion: the user confirms before it is applied.
    """
    file_headers = {normalize_header(h) for h in headers} - {""}
    if not file_headers:
        return []
    suggestions: list[ProfileSuggestion] = []
    for profile in profiles:
        try:
            known = set(load_defaults(profile).columns)
        except MappingRejectedError:
            continue  # a broken profile is never suggested; the admin sees it on its own page
        overlap = len(file_headers & known) / len(file_headers)
        if overlap >= MIN_PROFILE_OVERLAP:
            suggestions.append(ProfileSuggestion(profile.id, profile.name, overlap))
    return sorted(suggestions, key=lambda s: (-s.overlap, s.name))


def list_active_profiles(db: Session) -> list[SourceProfile]:
    """Active source profiles, by name (what an uploader may choose from)."""
    return list(
        db.execute(
            select(SourceProfile)
            .where(SourceProfile.is_active.is_(True))
            .order_by(SourceProfile.name)
        ).scalars()
    )


# --- the saved mapping ------------------------------------------------------------------------


def _saved_rows(db: Session, import_id: uuid.UUID) -> list[ColumnMapping]:
    """The column_mappings rows of an import, in column order."""
    return list(
        db.execute(
            select(ColumnMapping)
            .where(ColumnMapping.import_file_id == import_id)
            .order_by(ColumnMapping.column_index)
        ).scalars()
    )


def blocking_issues(columns: Sequence[MappingColumn]) -> tuple[str, ...]:
    """Codes of what stops "start import": a mandatory field (D-069) that no column fills.

    This blocks the wizard step so the user can fix the mapping; it never rejects the file
    (D-068).
    """
    mapped = {c.target_field for c in columns if c.target_field is not None}
    return tuple(f"{key}_not_mapped" for key in REQUIRED_FIELD_KEYS if key not in mapped)


def get_mapping_view(
    db: Session,
    actor: User,
    import_id: uuid.UUID,
    *,
    storage: FileStorage,
    limits: UploadLimits,
) -> MappingView:
    """The saved mapping if there is one, else a suggestion, plus profile suggestions.

    Raises:
        ImportNotFoundError: If the import is missing or not visible to the actor.
        MappingRejectedError: If the file cannot be read or the chosen profile is invalid.
        UploadRejectedError: If the stored file is no longer readable.
    """
    import_file = get_import_for_viewer(db, actor, import_id)
    headers = read_headers(import_file, storage, limits)
    saved = _saved_rows(db, import_id)
    if saved:
        columns = [
            MappingColumn(
                row.column_index,
                row.source_header or "",
                row.target_field,
                MappingOrigin.SAVED if row.target_field else MappingOrigin.UNMAPPED,
                row.is_reassigned,
            )
            for row in saved
        ]
    else:
        columns = suggest_columns(headers, load_defaults(_profile_of(db, import_file)))
    return MappingView(
        import_file=import_file,
        columns=tuple(columns),
        is_saved=bool(saved),
        profile_suggestions=tuple(suggest_profiles(headers, list_active_profiles(db))),
        blocking_issues=blocking_issues(columns),
    )


def _editable_import(db: Session, actor: User, import_id: uuid.UUID) -> ImportFile:
    """Load an import the actor may change (the uploader, before processing starts).

    Raises:
        ImportNotFoundError: If it is missing or not visible to the actor.
        MappingRejectedError: NOT_EDITABLE if the actor is not the uploader or the import has
            moved past mapping.
    """
    import_file = get_import_for_viewer(db, actor, import_id)
    if not can_change_import(actor, import_file) or import_file.status not in EDITABLE_STATUSES:
        raise MappingRejectedError(MappingErrorKind.NOT_EDITABLE, NOT_EDITABLE_MESSAGE)
    return import_file


def choose_profile(
    db: Session,
    actor: User,
    import_id: uuid.UUID,
    *,
    profile_id: uuid.UUID | None,
    default_country: str | None,
    ip_address: str | None = None,
) -> ImportFile:
    """Set the source profile and default country of an import (D-078); commits.

    A profile only changes the suggestions: a mapping already saved for the file is kept.

    Raises:
        ImportNotFoundError: If the import is missing or not visible to the actor.
        MappingRejectedError: NOT_EDITABLE, or UNKNOWN_PROFILE for a missing or inactive profile.
    """
    import_file = _editable_import(db, actor, import_id)
    if profile_id is not None:
        profile = db.get(SourceProfile, profile_id)
        if profile is None or not profile.is_active:
            raise MappingRejectedError(MappingErrorKind.UNKNOWN_PROFILE, UNKNOWN_PROFILE_MESSAGE)
    import_file.source_profile_id = profile_id
    import_file.default_country = (default_country or "").strip() or None
    import_file.status = ImportStatus.MAPPING
    record(
        db,
        action=AuditAction.IMPORT_MAPPING_CHANGED,
        actor_user_id=actor.id,
        object_type=AUDIT_OBJECT_TYPE,
        object_id=str(import_file.id),
        summary={
            "step": "profile_chosen",
            "source_profile_id": str(profile_id) if profile_id else None,
            "default_country": import_file.default_country,
        },
        ip_address=ip_address,
    )
    db.commit()
    return import_file


def save_mapping(
    db: Session,
    actor: User,
    import_id: uuid.UUID,
    targets: Mapping[int, str | None],
    *,
    storage: FileStorage,
    limits: UploadLimits,
    ip_address: str | None = None,
) -> MappingView:
    """Store the uploader's final mapping for the file, replacing any earlier one; commits.

    Args:
        targets: Column index -> target field key (None to ignore the column). Columns that are
            not listed are ignored too.

    A mapping that leaves a mandatory field unmapped is still saved: the problem is reported
    by blocking_issues so the user can fix it, and it stops "start import" later.

    Raises:
        ImportNotFoundError: If the import is missing or not visible to the actor.
        MappingRejectedError: NOT_EDITABLE; INVALID_MAPPING for an unknown column or field, or
            for one field assigned to two columns.
        UploadRejectedError: If the stored file is no longer readable.
    """
    import_file = _editable_import(db, actor, import_id)
    headers = read_headers(import_file, storage, limits)
    _validate_targets(targets, len(headers))

    suggested = {
        c.column_index: c.target_field
        for c in suggest_columns(headers, load_defaults(_profile_of(db, import_file)))
    }
    db.execute(delete(ColumnMapping).where(ColumnMapping.import_file_id == import_id))
    rows = [
        ColumnMapping(
            import_file_id=import_id,
            column_index=index,
            source_header=header,
            target_field=targets.get(index),
            # D-049: true when the user fixed or reassigned what the server suggested.
            is_reassigned=targets.get(index) != suggested[index],
        )
        for index, header in enumerate(headers)
    ]
    db.add_all(rows)
    import_file.status = ImportStatus.MAPPING
    columns = [
        MappingColumn(
            r.column_index,
            r.source_header or "",
            r.target_field,
            MappingOrigin.SAVED if r.target_field else MappingOrigin.UNMAPPED,
            r.is_reassigned,
        )
        for r in rows
    ]
    issues = blocking_issues(columns)
    record(
        db,
        action=AuditAction.IMPORT_MAPPING_CHANGED,
        actor_user_id=actor.id,
        object_type=AUDIT_OBJECT_TYPE,
        object_id=str(import_file.id),
        summary={
            "step": "mapping_saved",
            "mapped": sum(1 for c in columns if c.target_field),
            "reassigned": sum(1 for c in columns if c.is_reassigned),
            "unmapped": sum(1 for c in columns if not c.target_field),
            "blocking_issues": list(issues),
        },
        ip_address=ip_address,
    )
    db.commit()
    return MappingView(
        import_file=import_file,
        columns=tuple(columns),
        is_saved=True,
        profile_suggestions=tuple(suggest_profiles(headers, list_active_profiles(db))),
        blocking_issues=issues,
    )


def _validate_targets(targets: Mapping[int, str | None], column_count: int) -> None:
    """Check column indexes, field keys and that no field is used twice.

    Raises:
        MappingRejectedError: INVALID_MAPPING, with a fixed message naming the problem class.
    """
    if any(index < 0 or index >= column_count for index in targets):
        raise MappingRejectedError(
            MappingErrorKind.INVALID_MAPPING, "A mapped column does not exist in the file."
        )
    chosen = [key for key in targets.values() if key is not None]
    if any(key not in TARGET_FIELDS_BY_KEY for key in chosen):
        raise MappingRejectedError(MappingErrorKind.INVALID_MAPPING, "Unknown target field.")
    if len(chosen) != len(set(chosen)):
        raise MappingRejectedError(
            MappingErrorKind.INVALID_MAPPING, "Each field can be mapped from only one column."
        )


def save_mapping_as_default(
    db: Session,
    actor: User,
    import_id: uuid.UUID,
    profile_id: uuid.UUID,
    *,
    ip_address: str | None = None,
) -> SourceProfile:
    """Merge the import's saved mapping into a profile's defaults for later files; commits.

    Only the caller's permission (MANAGE_SOURCE_PROFILES, admins, D-049) is checked by the
    route. Columns with no header cannot be remembered (a header is the key, D-040) and are
    skipped. Existing defaults for other headers, and the profile's formats, are kept.

    Raises:
        ImportNotFoundError: If the import is missing or not visible to the actor.
        MappingRejectedError: MAPPING_NOT_SAVED if the import has no saved mapping;
            UNKNOWN_PROFILE; INVALID_PROFILE; INVALID_MAPPING if two columns with the same
            header text were mapped to different fields.
    """
    import_file = get_import_for_viewer(db, actor, import_id)
    saved = _saved_rows(db, import_id)
    if not saved:
        raise MappingRejectedError(MappingErrorKind.MAPPING_NOT_SAVED, MAPPING_NOT_SAVED_MESSAGE)
    rows = [r for r in saved if r.target_field and r.source_header]
    profile = db.get(SourceProfile, profile_id)
    if profile is None:
        raise MappingRejectedError(MappingErrorKind.UNKNOWN_PROFILE, UNKNOWN_PROFILE_MESSAGE)
    defaults = load_defaults(profile)

    learned: dict[str, str] = {}
    for row in rows:
        key = normalize_header(row.source_header or "")
        if learned.setdefault(key, row.target_field or "") != row.target_field:
            raise MappingRejectedError(
                MappingErrorKind.INVALID_MAPPING,
                "Two columns with the same header are mapped to different fields.",
            )
    merged = MappingDefaults(
        columns={**defaults.columns, **learned}, formats=dict(defaults.formats)
    )
    # A new dict is assigned (not mutated in place) so SQLAlchemy sees the JSONB change.
    profile.mapping_defaults = merged.model_dump(mode="json")
    record(
        db,
        action=AuditAction.SOURCE_PROFILE_UPDATED,
        actor_user_id=actor.id,
        object_type=PROFILE_AUDIT_OBJECT_TYPE,
        object_id=str(profile.id),
        summary={
            "step": "mapping_defaults_saved",
            "import_file_id": str(import_file.id),
            "columns_saved": len(learned),
        },
        ip_address=ip_address,
    )
    db.commit()
    return profile


# --- applying a mapping to rows ---------------------------------------------------------------


def mapped_columns(db: Session, import_id: uuid.UUID) -> list[MappedColumn]:
    """The saved mapping as the row mapper needs it (ignored columns left out).

    Raises:
        MappingRejectedError: MAPPING_NOT_SAVED if the import has no saved mapping.
    """
    rows = _saved_rows(db, import_id)
    if not rows:
        raise MappingRejectedError(MappingErrorKind.MAPPING_NOT_SAVED, MAPPING_NOT_SAVED_MESSAGE)
    return [MappedColumn(r.column_index, r.target_field) for r in rows if r.target_field]


def import_formats(db: Session, import_file: ImportFile) -> dict[str, FieldFormat]:
    """The parsing hints of the import's chosen profile (empty when none was chosen)."""
    return dict(load_defaults(_profile_of(db, import_file)).formats)


def apply_mapping(
    cells: Sequence[object],
    columns: Sequence[MappedColumn],
    formats: Mapping[str, FieldFormat],
) -> MappedRow:
    """Turn one file row into SourceRow values by reading the mapped columns.

    Every mapped field appears in values (None when the cell is blank or unreadable). A cell
    that cannot be converted adds a warning; the row is still delivered (D-068). The email text
    is also returned exactly as it appeared, for SourceRow.raw_email.
    """
    values: dict[str, JsonScalar] = {}
    warnings: list[CellWarning] = []
    raw_email: str | None = None
    for column in columns:
        cell = cells[column.column_index] if column.column_index < len(cells) else None
        field = TARGET_FIELDS_BY_KEY[column.target_field]
        converted = convert_cell(cell, field.value_type, formats.get(field.key, DEFAULT_FORMAT))
        values[field.key] = converted.value
        if converted.warning is not None:
            warnings.append(CellWarning(field.key, converted.warning))
        if field.key == "email" and not is_blank(cell):
            raw_email = cell if isinstance(cell, str) else str(cell)
    return MappedRow(values=values, raw_email=raw_email, warnings=tuple(warnings))
