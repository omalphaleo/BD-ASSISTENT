"""Test factories for the imports tables: files, profiles, mappings, raw rows, reports, changes.

Needed so tests build valid synthetic import data in one line; each factory creates the parent
rows it needs (a file, a report, a person) when none is passed. Reuses the core and leads
factories for users and people. All data is synthetic.
"""

import hashlib

from sqlalchemy.orm import Session

from app.imports.models import (
    ColumnMapping,
    ImportChange,
    ImportFile,
    ImportReport,
    RawRow,
    SourceProfile,
)
from app.leads.models import Person
from factories.common import next_number, persist
from factories.leads import make_person


def make_source_profile(session: Session, **overrides: object) -> SourceProfile:
    """Insert an active source profile with a unique name."""
    fields: dict[str, object] = {"name": f"Profile {next_number()}", "layout": "apollo"}
    return persist(session, SourceProfile(**{**fields, **overrides}))


def make_import_file(session: Session, **overrides: object) -> ImportFile:
    """Insert an import file with a unique, valid SHA-256 hex digest and no uploader."""
    number = next_number()
    fields: dict[str, object] = {
        "sha256": hashlib.sha256(f"file-{number}".encode()).hexdigest(),
        "filename": f"leads{number}.csv",
    }
    return persist(session, ImportFile(**{**fields, **overrides}))


def make_column_mapping(
    session: Session, *, import_file: ImportFile | None = None, **overrides: object
) -> ColumnMapping:
    """Insert a column mapping; the column index is unique so a file can hold several."""
    fields: dict[str, object] = {
        "import_file_id": (import_file or make_import_file(session)).id,
        "column_index": next_number(),
        "source_header": "Email",
        "target_field": "email",
    }
    return persist(session, ColumnMapping(**{**fields, **overrides}))


def make_raw_row(
    session: Session, *, import_file: ImportFile | None = None, **overrides: object
) -> RawRow:
    """Insert a raw row; the row number is unique so a file can hold several.

    Raw rows are immutable once stored (D-099): tests may insert them but never update them.
    """
    fields: dict[str, object] = {
        "import_file_id": (import_file or make_import_file(session)).id,
        "row_number": next_number(),
        "original_values": {"Email": "Jane@Example.com", "First Name": "Jane"},
        "email_normalized": "jane@example.com",
    }
    return persist(session, RawRow(**{**fields, **overrides}))


def make_import_report(
    session: Session, *, import_file: ImportFile | None = None, **overrides: object
) -> ImportReport:
    """Insert the (single) report of an import file with all counts at zero."""
    fields: dict[str, object] = {"import_file_id": (import_file or make_import_file(session)).id}
    return persist(session, ImportReport(**{**fields, **overrides}))


def make_import_change(
    session: Session,
    *,
    report: ImportReport | None = None,
    person: Person | None = None,
    **overrides: object,
) -> ImportChange:
    """Insert a change summary line of a report for one person (one per report and person)."""
    fields: dict[str, object] = {
        "import_report_id": (report or make_import_report(session)).id,
        "person_id": (person or make_person(session)).id,
        # The shape W2 writes: a list of leads.contracts.FieldChange objects.
        "changes": [{"field": "title", "old": "Engineer", "new": "Senior Engineer"}],
    }
    return persist(session, ImportChange(**{**fields, **overrides}))
