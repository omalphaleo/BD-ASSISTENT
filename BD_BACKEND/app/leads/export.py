"""CSV export of lead search results, with an audit event (M3-A5, D-087, D-024).

Needed so BD can download the leads of the current filter, as they could from Apollo (D-024),
within what they can already see (D-087: every BD user sees every lead, D-001, D-026). The rows
come from the same filter and sort as search (leads.search), so the file always matches the
screen; eligibility reasons come from compliance.eligibility so the export never re-defines a
rule. Every cell is neutralised against formula injection (core.csv_safety) and every export is
audited with the filter and the row count, never the rows (D-087). The file is built in memory
under a row cap, like the import downloads (D-110).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.services import AuditAction, record
from app.compliance.contracts import EligibilityContext, EligibilityReason, EligibilityWarning
from app.compliance.eligibility import build_context, reason_expression, warning_expression
from app.core.csv_safety import csv_text
from app.core.models import User
from app.leads.filters import FilterSet, SortDirection, SortField
from app.leads.models import Company, Person
from app.leads.search import apply_filters, load_page_facts, order_by_terms, to_row
from app.leads.search_schemas import SearchRow

# Most leads one export may hold; more matches are refused, never cut (M3-A5 decision 3).
MAX_EXPORT_ROWS = 50_000
# People handled per round of fact queries, so memory and query size stay small.
BATCH_SIZE = 1_000

LIST_SEPARATOR = ";"
YES = "yes"
NO = "no"

EXPORT_HEADER = (
    "first_name",
    "last_name",
    "title",
    "seniority",
    "city",
    "state",
    "country",
    "company",
    "industry",
    "employee_count",
    "company_hq_city",
    "company_hq_state",
    "company_hq_country",
    "email",
    "email_verification",
    "owner",
    "status_flags",
    "last_contacted_at",
    "eligible",
    "ineligible_reasons",
    "warnings",
    "opted_out",
)


class ExportTooLargeError(Exception):
    """More leads match the filter than one export may hold.

    Attributes:
        total: How many leads match.
        limit: The most one export may hold.
    """

    def __init__(self, total: int, limit: int) -> None:
        super().__init__(f"{total} leads match; one export holds at most {limit}")
        self.total = total
        self.limit = limit


@dataclass(frozen=True, slots=True)
class ExportResult:
    """A finished export: the CSV text and how many leads it holds."""

    csv: str
    row_count: int


@dataclass(frozen=True, slots=True)
class _Eligibility:
    """The eligibility columns of one person."""

    reasons: list[EligibilityReason]
    warnings: list[EligibilityWarning]


def _load_eligibility(
    db: Session, person_ids: Sequence[UUID], ctx: EligibilityContext
) -> dict[UUID, _Eligibility]:
    """Evaluate every eligibility reason and warning for the people, in one query.

    Uses the same SQL expressions as search ("eligible only" and the badges), so the file and
    the screen cannot disagree.
    """
    reason_columns = [reason_expression(r, ctx).label(r.value) for r in EligibilityReason]
    warning_columns = [warning_expression(w, ctx).label(w.value) for w in EligibilityWarning]
    rows = db.execute(
        select(Person.id, *reason_columns, *warning_columns).where(Person.id.in_(person_ids))
    ).all()
    return {
        row.id: _Eligibility(
            reasons=[r for r in EligibilityReason if getattr(row, r.value)],
            warnings=[w for w in EligibilityWarning if getattr(row, w.value)],
        )
        for row in rows
    }


def _format_time(value: datetime | None) -> str:
    """A timestamp as ISO 8601 text, or an empty cell."""
    return value.isoformat() if value is not None else ""


def _csv_row(row: SearchRow, eligibility: _Eligibility) -> list[object]:
    """One CSV line for a lead, in EXPORT_HEADER order."""
    company = row.company
    email = row.primary_email
    return [
        row.first_name,
        row.last_name,
        row.title,
        row.seniority,
        row.city,
        row.state,
        row.country,
        company.name if company else None,
        company.industry if company else None,
        company.employee_count if company else None,
        company.hq_city if company else None,
        company.hq_state if company else None,
        company.hq_country if company else None,
        email.address if email else None,
        email.verification_status.value if email else None,
        row.owner.name if row.owner else None,
        LIST_SEPARATOR.join(flag.value for flag in row.flags),
        _format_time(row.last_contacted_at),
        NO if eligibility.reasons else YES,
        LIST_SEPARATOR.join(reason.value for reason in eligibility.reasons),
        LIST_SEPARATOR.join(warning.value for warning in eligibility.warnings),
        YES if EligibilityReason.OPTED_OUT in eligibility.reasons else NO,
    ]


def export_leads(
    db: Session,
    actor: User,
    filters: FilterSet,
    *,
    sort: SortField = SortField.NAME,
    direction: SortDirection = SortDirection.ASC,
    ip_address: str | None = None,
) -> ExportResult:
    """Build the CSV of every lead matching the filters and audit the export (D-087).

    The same filters give the same leads as search (default view, "eligible only", "show
    opted-out"). The audit event holds the filter, the order and the row count, never the rows.

    Args:
        db: Database session.
        actor: The signed-in user; the endpoint has checked EXPORT_CSV.
        filters: The validated search definition.
        sort: Column to order by.
        direction: Ascending or descending.
        ip_address: Client address for the audit event.

    Raises:
        ExportTooLargeError: More than MAX_EXPORT_ROWS leads match. Nothing is audited.
    """
    ctx = build_context(db)
    join = Person.company_id == Company.id
    total = (
        db.scalar(
            apply_filters(
                select(func.count(Person.id)).select_from(Person).outerjoin(Company, join),
                filters,
                ctx,
            )
        )
        or 0
    )
    if total > MAX_EXPORT_ROWS:
        raise ExportTooLargeError(total, MAX_EXPORT_ROWS)

    pairs = db.execute(
        apply_filters(select(Person, Company).outerjoin(Company, join), filters, ctx).order_by(
            *order_by_terms(sort, direction)
        )
    ).all()
    lines: list[list[object]] = []
    for start in range(0, len(pairs), BATCH_SIZE):
        batch = pairs[start : start + BATCH_SIZE]
        facts = load_page_facts(db, [person for person, _ in batch], ctx)
        eligibility = _load_eligibility(db, [person.id for person, _ in batch], ctx)
        lines.extend(
            _csv_row(to_row(person, company, facts), eligibility[person.id])
            for person, company in batch
        )

    record(
        db,
        action=AuditAction.EXPORT_LEADS_DOWNLOADED,
        actor_user_id=actor.id,
        object_type="lead_export",
        summary={
            "filters": filters.model_dump(mode="json"),
            "sort": sort.value,
            "direction": direction.value,
            "row_count": len(lines),
        },
        ip_address=ip_address,
    )
    db.commit()
    return ExportResult(csv=csv_text(EXPORT_HEADER, lines), row_count=len(lines))
