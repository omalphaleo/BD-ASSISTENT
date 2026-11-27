"""The single eligibility service: which leads may be contacted, and why not (M3-A1).

Needed because search, campaigns, drafting and sending must never disagree about who can be
contacted (plan section 14 G, skill outreach-compliance). Each rule is written once as a pair:
a SQL expression for bulk search and a record check for one person. tests/test_eligibility_*
compares both over generated data (parity), so they cannot drift. The service only reads
tables and never writes, so it adds no audit event.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, Select, and_, exists, false, func, or_, select
from sqlalchemy.orm import Session

from app.compliance.contracts import (
    EligibilityContext,
    EligibilityReason,
    EligibilityResult,
    EligibilityWarning,
)
from app.compliance.models import OptOut
from app.core.clock import now as clock_now
from app.leads.engagement import read_cooling_off_days
from app.leads.models import (
    DuplicateCandidate,
    DuplicateStatus,
    EmailType,
    EmailVerificationStatus,
    LeadStatusFlag,
    LeadStatusFlagType,
    Person,
    PersonEmail,
    Touch,
    TouchChannel,
    TouchDirection,
)

# Flags that put a lead in a sales conversation and keep it out of new campaigns (D-101).
# Customer, partner, competitor and in-conversation flags do not block (D-065).
BLOCKING_FLAGS = frozenset({LeadStatusFlagType.QUALIFIED, LeadStatusFlagType.HANDED_OFF_TO_SALES})


@dataclass(frozen=True, slots=True)
class PersonFacts:
    """Everything the record checks need about one person, loaded once.

    Attributes:
        person: The lead being judged.
        emails: All the person's addresses.
        opted_out_addresses: The person's normalized addresses with an active opt-out.
        flags: Status flags currently set on the person.
        has_open_duplicate: True when an open duplicate pair involves the person.
        recent_outbound_count: Outbound emails inside the contact-limit window.
    """

    person: Person
    emails: tuple[PersonEmail, ...]
    opted_out_addresses: frozenset[str]
    flags: frozenset[LeadStatusFlagType]
    has_open_duplicate: bool
    recent_outbound_count: int


def _cooling_off_cutoff(ctx: EligibilityContext) -> datetime:
    """Return the earliest last-contact time that still counts as inside cooling-off.

    Shared by the SQL and record versions so the boundary is identical: a contact exactly
    cooling_off_days ago has already ended its cooling-off.
    """
    return ctx.now - timedelta(days=ctx.cooling_off_days)


def _window_start(ctx: EligibilityContext) -> datetime:
    """Return the start of the contact-limit window (a touch exactly on it still counts)."""
    return ctx.now - timedelta(days=ctx.contact_window_days)


def _is_usable(email: PersonEmail) -> bool:
    """A usable address is a work address not marked invalid (D-072, D-073)."""
    return email.type == EmailType.WORK and not email.is_invalid


def _outbound_in_window(ctx: EligibilityContext) -> list[ColumnElement[bool]]:
    """Conditions selecting the outbound email touches that count toward the contact limit.

    Every outbound email counts whatever its later status (decision 6). The window has no
    upper bound: touches are never recorded in the future.
    """
    return [
        Touch.channel == TouchChannel.EMAIL,
        Touch.direction == TouchDirection.OUTBOUND,
        Touch.occurred_at >= _window_start(ctx),
    ]


# --- SQL versions: boolean expressions over the people table ---


def _opted_out_sql(ctx: EligibilityContext) -> ColumnElement[bool]:
    """Any address of the person has an active opt-out (D-066, search assumption of 2026-11-02)."""
    return exists().where(
        PersonEmail.person_id == Person.id,
        OptOut.email_normalized == PersonEmail.normalized_address,
        OptOut.removed_at.is_(None),
    )


def _no_usable_email_sql(ctx: EligibilityContext) -> ColumnElement[bool]:
    """The person has no work address that is not invalid."""
    return ~exists().where(
        PersonEmail.person_id == Person.id,
        PersonEmail.type == EmailType.WORK,
        PersonEmail.is_invalid.is_(False),
    )


def _replied_sql(ctx: EligibilityContext) -> ColumnElement[bool]:
    """The person has replied."""
    return Person.replied_at.is_not(None)


def _blocking_flag_sql(ctx: EligibilityContext) -> ColumnElement[bool]:
    """The person is flagged Qualified or Handed Off to Sales."""
    return exists().where(
        LeadStatusFlag.person_id == Person.id,
        LeadStatusFlag.flag_type.in_(BLOCKING_FLAGS),
    )


def _possible_duplicate_sql(ctx: EligibilityContext) -> ColumnElement[bool]:
    """An open duplicate pair involves the person, on either side."""
    return exists().where(
        DuplicateCandidate.status == DuplicateStatus.OPEN,
        or_(
            DuplicateCandidate.person_a_id == Person.id,
            DuplicateCandidate.person_b_id == Person.id,
        ),
    )


def _cooling_off_sql(ctx: EligibilityContext) -> ColumnElement[bool]:
    """The person was last contacted inside the cooling-off period."""
    return and_(
        Person.last_contacted_at.is_not(None),
        Person.last_contacted_at > _cooling_off_cutoff(ctx),
    )


def _unverified_email_sql(ctx: EligibilityContext) -> ColumnElement[bool]:
    """SQL twin of the unverified-email warning (D-042): usable addresses exist, none verified.

    A warning, not a blocking rule, so it is not in _RULES; search uses it for a badge.
    """
    usable = (
        PersonEmail.person_id == Person.id,
        PersonEmail.type == EmailType.WORK,
        PersonEmail.is_invalid.is_(False),
    )
    verified = PersonEmail.verification_status == EmailVerificationStatus.VERIFIED
    return and_(exists().where(*usable), ~exists().where(*usable, verified))


def _contact_limit_sql(ctx: EligibilityContext) -> ColumnElement[bool]:
    """The person already has contact_limit or more outbound emails in the window."""
    recent = (
        select(func.count())
        .select_from(Touch)
        .where(Touch.person_id == Person.id, *_outbound_in_window(ctx))
        .correlate(Person)
        .scalar_subquery()
    )
    return recent >= ctx.contact_limit


# --- Record versions: pure checks over PersonFacts ---


def _opted_out_record(facts: PersonFacts, ctx: EligibilityContext) -> bool:
    """Record twin of _opted_out_sql."""
    return bool(facts.opted_out_addresses)


def _no_usable_email_record(facts: PersonFacts, ctx: EligibilityContext) -> bool:
    """Record twin of _no_usable_email_sql."""
    return not any(_is_usable(email) for email in facts.emails)


def _replied_record(facts: PersonFacts, ctx: EligibilityContext) -> bool:
    """Record twin of _replied_sql."""
    return facts.person.replied_at is not None


def _blocking_flag_record(facts: PersonFacts, ctx: EligibilityContext) -> bool:
    """Record twin of _blocking_flag_sql."""
    return bool(facts.flags & BLOCKING_FLAGS)


def _possible_duplicate_record(facts: PersonFacts, ctx: EligibilityContext) -> bool:
    """Record twin of _possible_duplicate_sql."""
    return facts.has_open_duplicate


def _cooling_off_record(facts: PersonFacts, ctx: EligibilityContext) -> bool:
    """Record twin of _cooling_off_sql (same cutoff, same strict comparison)."""
    last_contacted = facts.person.last_contacted_at
    return last_contacted is not None and last_contacted > _cooling_off_cutoff(ctx)


def _contact_limit_record(facts: PersonFacts, ctx: EligibilityContext) -> bool:
    """Record twin of _contact_limit_sql."""
    return facts.recent_outbound_count >= ctx.contact_limit


@dataclass(frozen=True, slots=True)
class _Rule:
    """One eligibility rule: its reason, SQL expression and record check, defined together."""

    reason: EligibilityReason
    sql: Callable[[EligibilityContext], ColumnElement[bool]]
    record: Callable[[PersonFacts, EligibilityContext], bool]


# The one list of rules, in EligibilityReason order. Adding a rule means adding one entry here.
_RULES: tuple[_Rule, ...] = (
    _Rule(EligibilityReason.OPTED_OUT, _opted_out_sql, _opted_out_record),
    _Rule(EligibilityReason.NO_USABLE_EMAIL, _no_usable_email_sql, _no_usable_email_record),
    _Rule(EligibilityReason.REPLIED, _replied_sql, _replied_record),
    _Rule(EligibilityReason.QUALIFIED_OR_HANDED_OFF, _blocking_flag_sql, _blocking_flag_record),
    _Rule(
        EligibilityReason.POSSIBLE_DUPLICATE, _possible_duplicate_sql, _possible_duplicate_record
    ),
    _Rule(EligibilityReason.COOLING_OFF, _cooling_off_sql, _cooling_off_record),
    _Rule(EligibilityReason.CONTACT_LIMIT, _contact_limit_sql, _contact_limit_record),
)
_RULES_BY_REASON = {rule.reason: rule for rule in _RULES}


def build_context(db: Session) -> EligibilityContext:
    """Return the context for "now": the clock time and the cooling-off days from Settings."""
    return EligibilityContext(now=clock_now(), cooling_off_days=read_cooling_off_days(db))


def reason_expression(reason: EligibilityReason, ctx: EligibilityContext) -> ColumnElement[bool]:
    """Return the SQL condition that is true for people blocked by one reason.

    Use it inside any query that selects from people: for result badges, or to filter
    "opted out" and "cooling off" leads. It is the bulk twin of the record check.
    """
    return _RULES_BY_REASON[reason].sql(ctx)


_WARNING_SQL: dict[EligibilityWarning, Callable[[EligibilityContext], ColumnElement[bool]]] = {
    EligibilityWarning.UNVERIFIED_EMAIL: _unverified_email_sql,
}


def warning_expression(warning: EligibilityWarning, ctx: EligibilityContext) -> ColumnElement[bool]:
    """Return the SQL condition that is true for people who carry one warning.

    The bulk twin of the record check inside check_eligibility(); tests/test_eligibility_parity
    compares the two. Use it for result badges.
    """
    return _WARNING_SQL[warning](ctx)


def ineligible_expression(ctx: EligibilityContext) -> ColumnElement[bool]:
    """Return the SQL condition that is true for people blocked by at least one reason."""
    return or_(false(), *(rule.sql(ctx) for rule in _RULES))


def eligible_queryset(ctx: EligibilityContext) -> Select[tuple[Person]]:
    """Return a query for every person who may be contacted; callers add filters and paging."""
    return select(Person).where(~ineligible_expression(ctx))


def load_facts(db: Session, person: Person, ctx: EligibilityContext) -> PersonFacts:
    """Load the rows the record checks need for one person (a handful of small queries)."""
    emails = tuple(db.scalars(select(PersonEmail).where(PersonEmail.person_id == person.id)).all())
    addresses = {email.normalized_address for email in emails}
    opted_out = (
        frozenset(
            db.scalars(
                select(OptOut.email_normalized).where(
                    OptOut.email_normalized.in_(addresses), OptOut.removed_at.is_(None)
                )
            ).all()
        )
        if addresses
        else frozenset()
    )
    flags = frozenset(
        db.scalars(select(LeadStatusFlag.flag_type).where(LeadStatusFlag.person_id == person.id))
    )
    has_open_duplicate = (
        db.execute(
            select(DuplicateCandidate.id)
            .where(
                DuplicateCandidate.status == DuplicateStatus.OPEN,
                or_(
                    DuplicateCandidate.person_a_id == person.id,
                    DuplicateCandidate.person_b_id == person.id,
                ),
            )
            .limit(1)
        ).first()
        is not None
    )
    recent_outbound_count = db.scalar(
        select(func.count())
        .select_from(Touch)
        .where(Touch.person_id == person.id, *_outbound_in_window(ctx))
    )
    return PersonFacts(
        person=person,
        emails=emails,
        opted_out_addresses=opted_out,
        flags=flags,
        has_open_duplicate=has_open_duplicate,
        recent_outbound_count=recent_outbound_count or 0,
    )


def _warnings(facts: PersonFacts) -> tuple[EligibilityWarning, ...]:
    """Cautions that do not block: usable addresses exist but none is verified (D-042)."""
    usable = [email for email in facts.emails if _is_usable(email)]
    if usable and not any(
        email.verification_status == EmailVerificationStatus.VERIFIED for email in usable
    ):
        return (EligibilityWarning.UNVERIFIED_EMAIL,)
    return ()


def check_eligibility(db: Session, person: Person, ctx: EligibilityContext) -> EligibilityResult:
    """Say whether one person may be contacted, listing every reason that blocks them.

    Args:
        db: Open session; only reads happen.
        person: The lead to judge.
        ctx: Time and limits, usually from build_context(); tests pass a fixed one.

    Returns:
        An EligibilityResult whose reasons follow EligibilityReason order.
    """
    facts = load_facts(db, person, ctx)
    reasons = tuple(rule.reason for rule in _RULES if rule.record(facts, ctx))
    return EligibilityResult(reasons=reasons, warnings=_warnings(facts))


def eligible_person_ids(db: Session, ctx: EligibilityContext) -> set[uuid.UUID]:
    """Return the ids of every eligible person (a convenience for tests and small callers)."""
    return set(db.scalars(eligible_queryset(ctx).with_only_columns(Person.id)).all())
