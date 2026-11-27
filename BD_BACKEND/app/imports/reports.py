"""Import report and "what changed" summary, read from the finished import (M2-A5, D-050).

Needed so a user can trust an import's result: the seven totals, the reasons rows failed, and
for updated leads the old and new value of every changed field. The totals are not computed
here: the pipeline already counts them into the ImportReport chunk by chunk (imports.pipeline),
and W2's merge code writes the ImportChange rows. This module only reads them, for the report
and change routes (imports.reports_api) and for the CSV downloads (imports.downloads). The
summary is transient (D-008): it is a per-import view, not a per-lead history.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.models import User
from app.imports.errors import ReportErrorKind, ReportRejectedError
from app.imports.models import ImportChange, ImportFile, ImportReport, ImportStatus
from app.imports.upload import get_import_for_viewer
from app.leads.contracts import TARGET_FIELDS_BY_KEY, JsonScalar
from app.leads.models import Person, PersonEmail

NOT_FINISHED_MESSAGE = "The report is available when the import has finished."
# Leads per page of the change summary (decided for M2-A5).
CHANGES_PAGE_SIZE = 50
FINISHED_STATUSES = frozenset({ImportStatus.COMPLETED, ImportStatus.FAILED})


@dataclass(frozen=True, slots=True)
class FailureReason:
    """How many rows failed (rejected or quarantined) for one reason code."""

    code: str
    count: int


@dataclass(frozen=True, slots=True)
class FieldChangeView:
    """One changed field of one lead: the stored field key, its label and the old and new value."""

    field: str
    label: str
    old: JsonScalar
    new: JsonScalar


@dataclass(frozen=True, slots=True)
class LeadChangeView:
    """What one import changed on one updated lead, with the lead's name and email to find it."""

    person_id: uuid.UUID
    name: str
    email: str | None
    changes: Sequence[FieldChangeView]


@dataclass(frozen=True, slots=True)
class ChangesPage:
    """One page of the change summary and the total number of changed leads."""

    total: int
    page: int
    page_size: int
    items: Sequence[LeadChangeView]


@dataclass(frozen=True, slots=True)
class ReportView:
    """A finished import with its totals, reason breakdown and the number of changed leads."""

    import_file: ImportFile
    report: ImportReport
    failure_reasons: Sequence[FailureReason]
    changes_total: int


def get_finished_import(db: Session, actor: User, import_id: uuid.UUID) -> ImportFile:
    """Load an import the actor may view and require it to be COMPLETED or FAILED.

    A FAILED import keeps the chunks it committed, so its partial report stays readable. A
    running or unstarted import has no final totals, so nothing is shown or downloaded yet.

    Raises:
        ImportNotFoundError: If it does not exist or the actor may not see it.
        ReportRejectedError: NOT_FINISHED, while the import is not COMPLETED or FAILED.
    """
    import_file = get_import_for_viewer(db, actor, import_id)
    if import_file.status not in FINISHED_STATUSES:
        raise ReportRejectedError(ReportErrorKind.NOT_FINISHED, NOT_FINISHED_MESSAGE)
    return import_file


def get_report_for_finished_import(db: Session, import_file: ImportFile) -> ImportReport:
    """Return the import's report row.

    Raises:
        ReportRejectedError: NOT_FINISHED, if no report exists (the import never ran).
    """
    report = db.scalar(select(ImportReport).where(ImportReport.import_file_id == import_file.id))
    if report is None:
        raise ReportRejectedError(ReportErrorKind.NOT_FINISHED, NOT_FINISHED_MESSAGE)
    return report


def get_report(db: Session, actor: User, import_id: uuid.UUID) -> ReportView:
    """Return the totals, the reason breakdown and the changed-lead count of a finished import.

    Raises:
        ImportNotFoundError: If it does not exist or the actor may not see it.
        ReportRejectedError: NOT_FINISHED, while the import is not COMPLETED or FAILED.
    """
    import_file = get_finished_import(db, actor, import_id)
    report = get_report_for_finished_import(db, import_file)
    changes_total = db.scalar(
        select(func.count())
        .select_from(ImportChange)
        .where(ImportChange.import_report_id == report.id)
    )
    return ReportView(
        import_file=import_file,
        report=report,
        failure_reasons=_sorted_reasons(report.failure_reasons),
        changes_total=changes_total or 0,
    )


def _sorted_reasons(failure_reasons: object) -> list[FailureReason]:
    """The stored {code: count} mapping as a list, most frequent reason first."""
    if not isinstance(failure_reasons, Mapping):
        return []
    reasons = [
        FailureReason(code=str(code), count=int(count))
        for code, count in failure_reasons.items()
        if isinstance(count, int)
    ]
    return sorted(reasons, key=lambda reason: (-reason.count, reason.code))


def list_changes(db: Session, actor: User, import_id: uuid.UUID, page: int) -> ChangesPage:
    """Return one page (CHANGES_PAGE_SIZE leads) of what the import changed, in a stable order.

    Raises:
        ImportNotFoundError: If it does not exist or the actor may not see it.
        ReportRejectedError: NOT_FINISHED, while the import is not COMPLETED or FAILED.
    """
    import_file = get_finished_import(db, actor, import_id)
    report = get_report_for_finished_import(db, import_file)
    total = db.scalar(
        select(func.count())
        .select_from(ImportChange)
        .where(ImportChange.import_report_id == report.id)
    )
    rows = db.execute(
        changes_query(report.id)
        .limit(CHANGES_PAGE_SIZE)
        .offset((max(page, 1) - 1) * CHANGES_PAGE_SIZE)
    ).all()
    return ChangesPage(
        total=total or 0,
        page=max(page, 1),
        page_size=CHANGES_PAGE_SIZE,
        items=lead_change_views(db, rows),
    )


def changes_query(report_id: uuid.UUID) -> Select[tuple[ImportChange, Person]]:
    """The change rows of a report with their person, ordered the same for page and download."""
    return (
        select(ImportChange, Person)
        .join(Person, Person.id == ImportChange.person_id)
        .where(ImportChange.import_report_id == report_id)
        .order_by(Person.last_name, Person.first_name, ImportChange.id)
    )


def lead_change_views(
    db: Session, rows: Sequence[tuple[ImportChange, Person]]
) -> list[LeadChangeView]:
    """Turn change rows into views with the lead's display name, email and labelled changes."""
    emails = _display_emails(db, [person.id for _, person in rows])
    return [
        LeadChangeView(
            person_id=person.id,
            name=_full_name(person),
            email=emails.get(person.id),
            changes=_field_changes(change.changes),
        )
        for change, person in rows
    ]


def _full_name(person: Person) -> str:
    """First and last name joined, without a trailing space when there is no last name."""
    return f"{person.first_name} {person.last_name or ''}".strip()


def _display_emails(db: Session, person_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    """One address per person for display: the primary one, otherwise the earliest created."""
    if not person_ids:
        return {}
    found = db.execute(
        select(PersonEmail.person_id, PersonEmail.address)
        .where(PersonEmail.person_id.in_(person_ids))
        .order_by(PersonEmail.is_primary.desc(), PersonEmail.created_at, PersonEmail.id)
    ).all()
    emails: dict[uuid.UUID, str] = {}
    for person_id, address in found:
        emails.setdefault(person_id, address)  # the first row per person is the best one
    return emails


def _field_changes(changes: object) -> list[FieldChangeView]:
    """Read the stored list of {field, old, new} objects (leads.contracts.FieldChange).

    Items that do not have that shape are skipped, so one odd row cannot break the whole page.
    """
    if not isinstance(changes, list):
        return []
    views: list[FieldChangeView] = []
    for item in changes:
        if not isinstance(item, Mapping) or not isinstance(item.get("field"), str):
            continue
        key = item["field"]
        target = TARGET_FIELDS_BY_KEY.get(key)
        views.append(
            FieldChangeView(
                field=key,
                label=target.label if target else key,
                old=_scalar(item.get("old")),
                new=_scalar(item.get("new")),
            )
        )
    return views


def _scalar(value: object) -> JsonScalar:
    """A stored value as a JSON scalar; anything else (list, object) is shown as text."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)
