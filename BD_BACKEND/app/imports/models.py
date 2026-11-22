"""SQLAlchemy models for the imports module: uploaded files, profiles, raw rows and reports.

Needed so M2 import can keep every uploaded row exactly as received (D-099), remember which
mapping was used for each file (D-049), warn about re-uploaded files (D-109) and report what
each import did (D-050). Migration 0007 creates the same schema, including the trigger that
makes raw_rows immutable and the quarantine_records.raw_row_id foreign key that points here.
Tables only in M1 task A4: no service reads or writes them yet. Fixed-value columns are VARCHAR
plus a named CHECK (not native enums), as in the leads module.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import now
from app.core.model_helpers import TimestampMixin, enum_column, in_check, uuid_pk
from app.db import Base

# Lowercase hex SHA-256 digest: 64 characters.
SHA256_HEX_PATTERN = "^[0-9a-f]{64}$"

# The seven totals D-050 asks the import report to show, in display order.
REPORT_COUNT_COLUMNS = (
    "received",
    "imported",
    "updated",
    "unchanged",
    "duplicates_found",
    "quarantined",
    "rejected",
)


class ImportStatus(enum.StrEnum):
    """Lifecycle of an uploaded import file."""

    UPLOADED = "uploaded"
    MAPPING = "mapping"  # headers are being confirmed or reassigned (D-049)
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceProfile(TimestampMixin, Base):
    """A saved description of one kind of source file, edited by admins only (D-049).

    layout is free text because the three predefined layouts are not agreed yet; the
    import service validates it. mapping_defaults holds the saved header-to-field defaults,
    while column_mappings records what was actually used for each file.
    """

    __tablename__ = "source_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    layout: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_defaults: Mapped[object] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # SET NULL keeps the profile when its creator is deleted.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_source_profiles_created_by_users"),
        nullable=True,
    )

    __table_args__ = (UniqueConstraint("name", name="uq_source_profiles_name"),)


class ImportFile(TimestampMixin, Base):
    """One uploaded CSV or XLSX file. The file bytes are not stored, only its SHA-256.

    sha256 is deliberately not unique: re-uploading identical content shows a warning and
    the user may import anyway (D-109). The 50,000-row and 20 MB limits (D-110) are checked
    by the import service, not by the database.
    """

    __tablename__ = "import_files"

    id: Mapped[uuid.UUID] = uuid_pk()
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # SET NULL keeps the import history when the uploader is deleted.
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_import_files_uploaded_by_users"),
        nullable=True,
    )
    source_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "source_profiles.id",
            ondelete="SET NULL",
            name="fk_import_files_source_profile_id_source_profiles",
        ),
        nullable=True,
    )
    # Chosen per import; leads with no location data fall back to it (D-078).
    default_country: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # One sheet per import (D-110); NULL for CSV files.
    worksheet: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ImportStatus] = mapped_column(
        enum_column(ImportStatus),
        nullable=False,
        default=ImportStatus.UPLOADED,
        server_default=text("'uploaded'"),
    )
    row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    __table_args__ = (
        in_check("status", ImportStatus, "ck_import_files_status_valid"),
        CheckConstraint(f"sha256 ~ '{SHA256_HEX_PATTERN}'", name="ck_import_files_sha256_hex"),
        CheckConstraint("row_count >= 0", name="ck_import_files_row_count_nonnegative"),
        # Duplicate-file lookup (D-109).
        Index("ix_import_files_sha256", "sha256"),
        Index("ix_import_files_source_profile_id", "source_profile_id"),
        Index("ix_import_files_uploaded_by", "uploaded_by"),
    )


class ColumnMapping(TimestampMixin, Base):
    """How one column of one import file was mapped to a lead field (the mapping actually used).

    source_header may be empty because manual files can lack headers (D-049); target_field
    NULL means the column is ignored. Saved defaults live on source_profiles instead.
    """

    __tablename__ = "column_mappings"

    id: Mapped[uuid.UUID] = uuid_pk()
    import_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "import_files.id", ondelete="CASCADE", name="fk_column_mappings_import_file_id_files"
        ),
        nullable=False,
    )
    # Zero-based position in the sheet, so headerless or duplicate headers stay distinct.
    column_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_header: Mapped[str | None] = mapped_column(String(512), nullable=True)
    target_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # True when a user fixed or reassigned this header for the file (D-049).
    is_reassigned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    __table_args__ = (
        UniqueConstraint(
            "import_file_id", "column_index", name="uq_column_mappings_import_file_id_column_index"
        ),
        CheckConstraint("column_index >= 0", name="ck_column_mappings_column_index_nonnegative"),
    )


class RawRow(Base):
    """One uploaded row with its original values, never modified (D-099, D-008).

    A database trigger (migration 0007) rejects any UPDATE that changes the original
    columns; only person_id, the link to the lead, may change (release, merge, SET NULL).
    Rows are removed only by erase-person. There is no updated_at, because nothing about
    the original may change.
    """

    __tablename__ = "raw_rows"

    id: Mapped[uuid.UUID] = uuid_pk()
    # RESTRICT: a file with stored rows cannot be deleted; only erase-person removes rows.
    import_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "import_files.id", ondelete="RESTRICT", name="fk_raw_rows_import_file_id_import_files"
        ),
        nullable=False,
    )
    # One-based row number in the sheet.
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Header or column position to cell value, exactly as received.
    original_values: Mapped[object] = mapped_column(JSONB, nullable=False)
    # Lowercased, trimmed email found in the row: lets erase-person find rows that were
    # never linked to a person, such as quarantined ones (D-099).
    email_normalized: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # The lead this row created or updated. SET NULL when the person is deleted.
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("people.id", ondelete="SET NULL", name="fk_raw_rows_person_id_people"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )

    __table_args__ = (
        UniqueConstraint(
            "import_file_id", "row_number", name="uq_raw_rows_import_file_id_row_number"
        ),
        CheckConstraint("row_number >= 1", name="ck_raw_rows_row_number_positive"),
        CheckConstraint(
            "email_normalized = lower(email_normalized)",
            name="ck_raw_rows_email_normalized_lowercase",
        ),
        Index("ix_raw_rows_email_normalized", "email_normalized"),
        Index("ix_raw_rows_person_id", "person_id"),
    )


class ImportReport(TimestampMixin, Base):
    """Totals and reason-coded failures for one import (D-050); one report per file."""

    __tablename__ = "import_reports"

    id: Mapped[uuid.UUID] = uuid_pk()
    import_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "import_files.id", ondelete="CASCADE", name="fk_import_reports_import_file_id_files"
        ),
        nullable=False,
    )
    received: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    imported: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    updated: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    unchanged: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    duplicates_found: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    quarantined: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    rejected: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # Reason code to number of rows, e.g. {"personal_email_only": 12}.
    failure_reasons: Mapped[object] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("import_file_id", name="uq_import_reports_import_file_id"),
        *(
            CheckConstraint(f"{column} >= 0", name=f"ck_import_reports_{column}_nonnegative")
            for column in REPORT_COUNT_COLUMNS
        ),
    )


class ImportChange(Base):
    """What one import changed on one updated lead: the transient summary of D-050.

    Not a permanent per-lead history (D-008). Holds old and new personal values, so it is
    removed with the person (CASCADE). No expiry or cleanup job exists yet: the retention
    period is still unresolved.
    """

    __tablename__ = "import_changes"

    id: Mapped[uuid.UUID] = uuid_pk()
    import_report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "import_reports.id",
            ondelete="CASCADE",
            name="fk_import_changes_import_report_id_import_reports",
        ),
        nullable=False,
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE", name="fk_import_changes_person_id_people"),
        nullable=False,
    )
    # Field name to {"old": ..., "new": ...}.
    changes: Mapped[object] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )

    __table_args__ = (
        UniqueConstraint(
            "import_report_id", "person_id", name="uq_import_changes_import_report_id_person_id"
        ),
        Index("ix_import_changes_person_id", "person_id"),
    )
