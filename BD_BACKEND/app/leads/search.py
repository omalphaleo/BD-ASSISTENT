"""Lead search: a FilterSet becomes a query, a page of rows and the filter checkbox values (M3-A2).

Needed so BD can find leads by industry, size, place, title, technology, revenue, funding,
Salesforce use and status flags (D-024, D-025, D-063), with the default view, badges and
paging the requirements describe (Q-LEADS-07, D-106). The query is built only from FilterSet
fields; eligibility rules and badges come from compliance.eligibility so search never
re-defines them. Read-only: no writes and no audit event.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    ColumnElement,
    Select,
    Text,
    and_,
    exists,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.orm import Session

from app.compliance.contracts import EligibilityContext, EligibilityReason, EligibilityWarning
from app.compliance.eligibility import (
    build_context,
    ineligible_expression,
    reason_expression,
    warning_expression,
)
from app.core.models import User
from app.leads.filters import (
    SIZE_BAND_RANGES,
    FilterSet,
    SizeBand,
    SortDirection,
    SortField,
)
from app.leads.models import Company, LeadStatusFlag, LeadStatusFlagType, Person, PersonEmail
from app.leads.search_schemas import (
    Badge,
    CompanySummary,
    FilterOptionsResponse,
    OwnerSummary,
    PrimaryEmail,
    SearchResponse,
    SearchRow,
)

# Most values one filter-options list returns; a longer list is cut and reported as truncated.
MAX_FILTER_OPTIONS = 500

LIKE_ESCAPE = "\\"

# The badges that come from blocking eligibility reasons; unverified email is a warning.
_BADGE_REASONS: dict[Badge, EligibilityReason] = {
    Badge.COOLING_OFF: EligibilityReason.COOLING_OFF,
    Badge.REPLIED: EligibilityReason.REPLIED,
    Badge.POSSIBLE_DUPLICATE: EligibilityReason.POSSIBLE_DUPLICATE,
    Badge.OPTED_OUT: EligibilityReason.OPTED_OUT,
}


# --- Filters: one small function per kind of match ---


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so a typed "50%" or "a_b" is matched literally."""
    return (
        term.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", f"{LIKE_ESCAPE}%")
        .replace("_", f"{LIKE_ESCAPE}_")
    )


def _equals_any(column: ColumnElement[Any], values: Sequence[str]) -> ColumnElement[bool]:
    """Exact, case-insensitive match against any of the values."""
    return func.lower(column).in_([value.lower() for value in values])


def _contains_any(column: ColumnElement[Any], terms: Sequence[str]) -> ColumnElement[bool]:
    """Case-insensitive "contains" match against any of the terms."""
    return or_(*(column.ilike(f"%{_escape_like(t)}%", escape=LIKE_ESCAPE) for t in terms))


def _size_band_condition(bands: Sequence[SizeBand]) -> ColumnElement[bool]:
    """Employee count inside any chosen band (D-085); an unknown count matches no band."""
    clauses: list[ColumnElement[bool]] = []
    for band in bands:
        low, high = SIZE_BAND_RANGES[band]
        clause = Company.employee_count >= low
        if high is not None:
            clause = and_(clause, Company.employee_count <= high)
        clauses.append(clause)
    return or_(*clauses)


def _location_condition(
    person_column: ColumnElement[Any], company_column: ColumnElement[Any], values: Sequence[str]
) -> ColumnElement[bool]:
    """Match the person's own place OR the company headquarters (decision 4)."""
    return or_(_equals_any(person_column, values), _equals_any(company_column, values))


def _flag_exists(flags: Sequence[LeadStatusFlagType]) -> ColumnElement[bool]:
    """True when the person carries at least one of the flags."""
    return exists().where(
        LeadStatusFlag.person_id == Person.id, LeadStatusFlag.flag_type.in_(flags)
    )


def _filter_conditions(filters: FilterSet, ctx: EligibilityContext) -> list[ColumnElement[bool]]:
    """Return one SQL condition per filter that is set; they are combined with AND.

    Args:
        filters: The validated search definition.
        ctx: Eligibility inputs (clock time, cooling-off days) for the default view.
    """
    conditions: list[ColumnElement[bool]] = []
    if filters.industries:
        conditions.append(_equals_any(Company.industry, filters.industries))
    if filters.company_names:
        conditions.append(_contains_any(Company.name, filters.company_names))
    if filters.size_bands:
        conditions.append(_size_band_condition(filters.size_bands))
    if filters.countries:
        conditions.append(
            _location_condition(Person.country, Company.hq_country, filters.countries)
        )
    if filters.states:
        conditions.append(_location_condition(Person.state, Company.hq_state, filters.states))
    if filters.cities:
        conditions.append(_location_condition(Person.city, Company.hq_city, filters.cities))
    if filters.titles:
        conditions.append(_contains_any(Person.title, filters.titles))
    if filters.technologies:
        # PostgreSQL array overlap (&&): any chosen tag is present; the GIN index serves it.
        conditions.append(Company.technologies.op("&&")(literal(filters.technologies, ARRAY(Text))))
    if filters.uses_salesforce is not None:
        conditions.append(Company.uses_salesforce.is_(filters.uses_salesforce))
    if filters.revenue_min is not None:
        conditions.append(Company.annual_revenue >= filters.revenue_min)
    if filters.revenue_max is not None:
        conditions.append(Company.annual_revenue <= filters.revenue_max)
    if filters.funding_stages:
        conditions.append(_equals_any(Company.latest_funding_round_type, filters.funding_stages))
    if filters.flags_include:
        conditions.append(_flag_exists(filters.flags_include))
    if filters.flags_exclude:
        conditions.append(~_flag_exists(filters.flags_exclude))
    # Default view: everyone except opted-out leads (D-106, D-067); "show opted-out" adds them.
    if not filters.show_opted_out:
        conditions.append(~reason_expression(EligibilityReason.OPTED_OUT, ctx))
    if filters.eligible_only:
        conditions.append(~ineligible_expression(ctx))
    return conditions


def apply_filters(stmt: Select[Any], filters: FilterSet, ctx: EligibilityContext) -> Select[Any]:
    """Narrow a query over people (outer-joined to companies) by a FilterSet.

    Args:
        stmt: A select that includes Person and an outer join to Company.
        filters: The validated search definition.
        ctx: Eligibility inputs for the default view and "eligible only".

    Returns:
        The same query with every filter applied.
    """
    conditions = _filter_conditions(filters, ctx)
    return stmt.where(*conditions) if conditions else stmt


# --- Ordering ---


def _order_by(sort: SortField, direction: SortDirection) -> list[ColumnElement[Any]]:
    """Return the ORDER BY terms: the chosen column, empty values last, then id for stable pages."""
    text_columns: dict[SortField, list[ColumnElement[Any]]] = {
        SortField.NAME: [func.lower(Person.last_name), func.lower(Person.first_name)],
        SortField.COMPANY: [func.lower(Company.name)],
        SortField.TITLE: [func.lower(Person.title)],
        SortField.LAST_CONTACTED_AT: [Person.last_contacted_at],
        SortField.CREATED_AT: [Person.created_at],
    }
    ordered: list[ColumnElement[Any]] = []
    for column in text_columns[sort]:
        ordered.append(
            column.asc().nulls_last()
            if direction is SortDirection.ASC
            else column.desc().nulls_last()
        )
    # The id tiebreaker keeps paging stable when many leads share the same value.
    ordered.append(Person.id.asc())
    return ordered


# --- Extra facts for the rows on one page (one query each, never one per lead) ---


@dataclass(frozen=True, slots=True)
class _PageFacts:
    """Per-person facts gathered for one page of results."""

    primary_emails: dict[UUID, PrimaryEmail]
    flags: dict[UUID, list[LeadStatusFlagType]]
    owners: dict[UUID, OwnerSummary]
    badges: dict[UUID, list[Badge]]


def _load_badges(
    db: Session, person_ids: Sequence[UUID], ctx: EligibilityContext
) -> dict[UUID, list[Badge]]:
    """Compute every badge for the page's people in one query, using the eligibility SQL."""
    reason_columns = [
        reason_expression(reason, ctx).label(badge.value)
        for badge, reason in _BADGE_REASONS.items()
    ]
    warning_column = warning_expression(EligibilityWarning.UNVERIFIED_EMAIL, ctx).label(
        Badge.UNVERIFIED_EMAIL.value
    )
    rows = db.execute(
        select(Person.id, *reason_columns, warning_column).where(Person.id.in_(person_ids))
    ).all()
    badges: dict[UUID, list[Badge]] = {}
    for row in rows:
        # Badge declaration order, so the list is the same for every lead.
        badges[row.id] = [badge for badge in Badge if getattr(row, badge.value)]
    return badges


def _load_page_facts(db: Session, people: Sequence[Person], ctx: EligibilityContext) -> _PageFacts:
    """Gather primary emails, flags, owners and badges for the people on one page."""
    ids = [person.id for person in people]
    primary_emails = {
        email.person_id: PrimaryEmail(
            address=email.address, verification_status=email.verification_status
        )
        for email in db.scalars(
            select(PersonEmail).where(
                PersonEmail.person_id.in_(ids), PersonEmail.is_primary.is_(True)
            )
        )
    }
    flags: dict[UUID, list[LeadStatusFlagType]] = {}
    for person_id, flag_type in db.execute(
        select(LeadStatusFlag.person_id, LeadStatusFlag.flag_type)
        .where(LeadStatusFlag.person_id.in_(ids))
        .order_by(LeadStatusFlag.flag_type)
    ):
        flags.setdefault(person_id, []).append(flag_type)
    owner_ids = {person.owner_id for person in people if person.owner_id is not None}
    owners = {
        user_id: OwnerSummary(id=user_id, name=email)
        for user_id, email in db.execute(select(User.id, User.email).where(User.id.in_(owner_ids)))
    }
    return _PageFacts(primary_emails, flags, owners, _load_badges(db, ids, ctx))


def _to_row(person: Person, company: Company | None, facts: _PageFacts) -> SearchRow:
    """Assemble one result row from the person, their company and the page facts."""
    return SearchRow(
        person_id=person.id,
        first_name=person.first_name,
        last_name=person.last_name,
        title=person.title,
        seniority=person.seniority,
        city=person.city,
        state=person.state,
        country=person.country,
        company=None
        if company is None
        else CompanySummary(
            id=company.id,
            name=company.name,
            industry=company.industry,
            employee_count=company.employee_count,
            hq_city=company.hq_city,
            hq_state=company.hq_state,
            hq_country=company.hq_country,
        ),
        primary_email=facts.primary_emails.get(person.id),
        owner=facts.owners.get(person.owner_id) if person.owner_id else None,
        last_contacted_at=person.last_contacted_at,
        flags=facts.flags.get(person.id, []),
        badges=facts.badges.get(person.id, []),
    )


def search_leads(
    db: Session,
    filters: FilterSet,
    *,
    sort: SortField = SortField.NAME,
    direction: SortDirection = SortDirection.ASC,
    limit: int,
    offset: int,
) -> SearchResponse:
    """Run one search and return a page of rows plus the total number of matches.

    Every BD user sees every lead (D-001, D-026), so no per-user scoping is applied here.
    The caller's permission is checked by the endpoint.

    Args:
        db: Database session.
        filters: The validated search definition.
        sort: Column to order by.
        direction: Ascending or descending.
        limit: Page size (the endpoint caps it).
        offset: Rows to skip.
    """
    ctx = build_context(db)
    join = Person.company_id == Company.id
    total = db.scalar(
        apply_filters(
            select(func.count(Person.id)).select_from(Person).outerjoin(Company, join), filters, ctx
        )
    )
    page = db.execute(
        apply_filters(select(Person, Company).outerjoin(Company, join), filters, ctx)
        .order_by(*_order_by(sort, direction))
        .limit(limit)
        .offset(offset)
    ).all()
    facts = _load_page_facts(db, [person for person, _ in page], ctx) if page else None
    items = [_to_row(person, company, facts) for person, company in page] if facts else []
    return SearchResponse(items=items, total=total or 0, limit=limit, offset=offset)


# --- Filter checkbox values ---


def _distinct_values(db: Session, *columns: ColumnElement[Any]) -> tuple[list[str], bool]:
    """Return the distinct non-empty values of the columns, case-insensitively, and a cut flag.

    Several columns are merged (a location filter matches the person or the company). Values
    that differ only by case count once. At most MAX_FILTER_OPTIONS are returned.
    """
    merged = union_all(*(select(column.label("value")) for column in columns)).subquery()
    value = merged.c.value
    rows = db.scalars(
        select(func.min(value))
        .where(value.is_not(None), func.length(func.trim(value)) > 0)
        .group_by(func.lower(value))
        .order_by(func.lower(value))
        .limit(MAX_FILTER_OPTIONS + 1)
    ).all()
    return list(rows[:MAX_FILTER_OPTIONS]), len(rows) > MAX_FILTER_OPTIONS


def get_filter_options(db: Session) -> FilterOptionsResponse:
    """Return the values the filter checkboxes offer, read from the lead data.

    Fixed lists (size bands, flags) are always complete; the data-driven lists are capped
    and named in `truncated` when cut.
    """
    truncated: list[str] = []

    def options(name: str, *columns: ColumnElement[Any]) -> list[str]:
        values, cut = _distinct_values(db, *columns)
        if cut:
            truncated.append(name)
        return values

    return FilterOptionsResponse(
        industries=options("industries", Company.industry),
        countries=options("countries", Person.country, Company.hq_country),
        states=options("states", Person.state, Company.hq_state),
        cities=options("cities", Person.city, Company.hq_city),
        funding_stages=options("funding_stages", Company.latest_funding_round_type),
        technologies=options("technologies", func.unnest(Company.technologies)),
        size_bands=list(SizeBand),
        flags=list(LeadStatusFlagType),
        truncated=truncated,
    )
