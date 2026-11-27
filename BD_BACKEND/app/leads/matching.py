"""Finds the existing person and company an incoming row belongs to (M2-B3, D-077, D-092).

Needed so a re-import updates people instead of duplicating them: before merging, ingest_row
must know whether a row is someone already stored, someone new, or only possibly someone
stored. The functions here only read the database (plus record_possible_duplicate, which adds
one DuplicateCandidate row) and never commit; M2-B4's ingest_row decides what to do with the
answer. Callers pass already-normalized keys (leads/normalization.py).
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.leads.models import (
    Company,
    DuplicateCandidate,
    DuplicateStatus,
    Person,
    PersonEmail,
)

# Stored in DuplicateCandidate.reason for pairs raised by the name-plus-domain rule.
NAME_AND_COMPANY_DOMAIN_REASON = "name_and_company_domain"


class MatchStrength(StrEnum):
    """How sure a person match is: only CERTAIN may be merged automatically (D-092)."""

    NONE = "none"
    CERTAIN = "certain"
    POSSIBLE = "possible"


class PersonMatchRule(StrEnum):
    """Which clue found the person, in D-077 order (most reliable first)."""

    SOURCE_RECORD_ID = "source_record_id"
    EMAIL = "email"
    LINKEDIN_URL = "linkedin_url"
    NAME_AND_COMPANY_DOMAIN = "name_and_company_domain"


class CompanyMatchRule(StrEnum):
    """Which clue found the company, in D-077 order."""

    APOLLO_ACCOUNT_ID = "apollo_account_id"
    DOMAIN = "domain"
    NORMALIZED_NAME = "normalized_name"


@dataclass(frozen=True, slots=True)
class PersonKeys:
    """The normalized clues about one incoming person; any of them may be missing.

    Attributes:
        source_record_id: The source's own person id (Apollo Contact Id, D-041).
        emails: Normalized addresses of the row (primary first); personal and generic
            addresses are fine here, they still identify the same mailbox.
        linkedin_url: Output of normalize_linkedin_url.
        first_name: Normalized first name.
        last_name: Normalized last name.
        company_domain: Normalized company domain (work email domain, else website).
    """

    source_record_id: str | None = None
    emails: tuple[str, ...] = ()
    linkedin_url: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    company_domain: str | None = None


@dataclass(frozen=True, slots=True)
class PersonMatch:
    """The answer of find_person: who (if anyone), by which clue, and how sure.

    Attributes:
        strength: NONE (new person), CERTAIN (the same person) or POSSIBLE (maybe).
        person_id: The stored person; None only when strength is NONE.
        rule: The clue that found them; None only when strength is NONE.
    """

    strength: MatchStrength
    person_id: uuid.UUID | None = None
    rule: PersonMatchRule | None = None


@dataclass(frozen=True, slots=True)
class CompanyMatch:
    """The answer of find_company: the stored company and the clue, or neither."""

    company_id: uuid.UUID | None = None
    rule: CompanyMatchRule | None = None


NO_PERSON_MATCH = PersonMatch(MatchStrength.NONE)
NO_COMPANY_MATCH = CompanyMatch()


def _first_person_id(db: Session, query: Select[tuple[uuid.UUID]]) -> uuid.UUID | None:
    """Return the oldest person a query finds, so repeated imports pick the same one."""
    return db.execute(query.order_by(Person.created_at, Person.id).limit(1)).scalar()


def find_person(db: Session, keys: PersonKeys) -> PersonMatch:
    """Look for the stored person an incoming row refers to, trying clues in D-077 order.

    The first three clues (source id, email, LinkedIn link) identify a person for certain.
    Name plus company domain only makes a POSSIBLE match, because two people can share a
    name at one company; the caller then imports a separate record and raises a duplicate
    for review instead of merging (D-092). When several people share a clue the oldest wins.

    Returns:
        The match; NO_PERSON_MATCH when no clue finds anyone.
    """
    if keys.source_record_id:
        person_id = _first_person_id(
            db, select(Person.id).where(Person.source_record_id == keys.source_record_id)
        )
        if person_id:
            return PersonMatch(MatchStrength.CERTAIN, person_id, PersonMatchRule.SOURCE_RECORD_ID)

    if keys.emails:
        person_id = _first_person_id(
            db,
            select(Person.id)
            .join(PersonEmail, PersonEmail.person_id == Person.id)
            .where(PersonEmail.normalized_address.in_(keys.emails)),
        )
        if person_id:
            return PersonMatch(MatchStrength.CERTAIN, person_id, PersonMatchRule.EMAIL)

    if keys.linkedin_url:
        # People store the already-normalized link (B4 writes it that way).
        person_id = _first_person_id(
            db, select(Person.id).where(Person.linkedin_url == keys.linkedin_url)
        )
        if person_id:
            return PersonMatch(MatchStrength.CERTAIN, person_id, PersonMatchRule.LINKEDIN_URL)

    # Both names are required: a first name alone at one company is too weak a clue.
    if keys.first_name and keys.last_name and keys.company_domain:
        person_id = _first_person_id(
            db,
            select(Person.id)
            .join(Company, Company.id == Person.company_id)
            .where(
                func.lower(Person.first_name) == keys.first_name.lower(),
                func.lower(Person.last_name) == keys.last_name.lower(),
                Company.domain == keys.company_domain,
            ),
        )
        if person_id:
            return PersonMatch(
                MatchStrength.POSSIBLE, person_id, PersonMatchRule.NAME_AND_COMPANY_DOMAIN
            )

    return NO_PERSON_MATCH


@dataclass(frozen=True, slots=True)
class CompanyKeys:
    """The normalized clues about one incoming company; any of them may be missing.

    Attributes:
        apollo_account_id: The source's own company id (Apollo Account Id).
        domain: Normalized domain: the work-email domain first, the website as fallback.
        normalized_name: Output of normalize_company_name.
    """

    apollo_account_id: str | None = None
    domain: str | None = None
    normalized_name: str | None = None


def find_company(db: Session, keys: CompanyKeys) -> CompanyMatch:
    """Look for the stored company an incoming row refers to, in D-077 order.

    Apollo Account ID is unique, so it is certain. Domain comes next. Name is the weakest
    clue, so a company found by name is rejected when it visibly disagrees with the row
    (a different domain or a different Apollo Account ID): two firms can share a name.
    When several companies share a clue the oldest wins.

    Returns:
        The match; NO_COMPANY_MATCH when no clue finds a company.
    """
    if keys.apollo_account_id:
        company_id = db.execute(
            select(Company.id).where(Company.apollo_account_id == keys.apollo_account_id)
        ).scalar()
        if company_id:
            return CompanyMatch(company_id, CompanyMatchRule.APOLLO_ACCOUNT_ID)

    if keys.domain:
        company_id = db.execute(
            select(Company.id)
            .where(Company.domain == keys.domain)
            .order_by(Company.created_at, Company.id)
            .limit(1)
        ).scalar()
        if company_id:
            return CompanyMatch(company_id, CompanyMatchRule.DOMAIN)

    if keys.normalized_name:
        query = select(Company.id).where(Company.normalized_name == keys.normalized_name)
        if keys.domain:
            query = query.where(Company.domain.is_(None))
        if keys.apollo_account_id:
            query = query.where(Company.apollo_account_id.is_(None))
        company_id = db.execute(query.order_by(Company.created_at, Company.id).limit(1)).scalar()
        if company_id:
            return CompanyMatch(company_id, CompanyMatchRule.NORMALIZED_NAME)

    return NO_COMPANY_MATCH


def _ordered_pair(first: uuid.UUID, second: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Return the two ids smallest first, as duplicate_candidates stores every pair."""
    return (first, second) if first < second else (second, first)


def find_duplicate_decision(
    db: Session, person_id: uuid.UUID, other_person_id: uuid.UUID
) -> DuplicateCandidate | None:
    """Return the stored duplicate row for a pair of people (either order), if any."""
    person_a_id, person_b_id = _ordered_pair(person_id, other_person_id)
    return db.execute(
        select(DuplicateCandidate).where(
            DuplicateCandidate.person_a_id == person_a_id,
            DuplicateCandidate.person_b_id == person_b_id,
        )
    ).scalar_one_or_none()


def is_marked_not_duplicate(db: Session, person_id: uuid.UUID, other_person_id: uuid.UUID) -> bool:
    """True when a manager already decided these two people are different (D-092)."""
    decision = find_duplicate_decision(db, person_id, other_person_id)
    return decision is not None and decision.status == DuplicateStatus.NOT_DUPLICATE


def record_possible_duplicate(
    db: Session,
    person_id: uuid.UUID,
    other_person_id: uuid.UUID,
    reason: str = NAME_AND_COMPANY_DOMAIN_REASON,
) -> DuplicateCandidate | None:
    """Flag two people as a possible duplicate for a manager to review (D-092).

    Called by ingest_row after it has imported the uncertain row as a separate person. The
    pair is stored once, smallest id first. A pair that already has a row is left alone, so
    the same pair is never raised twice and a "not a duplicate" decision is remembered: it
    is not reopened by a later import.

    Returns:
        The new open candidate, or None when the pair already has a decision or is open.
    """
    if person_id == other_person_id:
        return None
    if find_duplicate_decision(db, person_id, other_person_id) is not None:
        return None
    person_a_id, person_b_id = _ordered_pair(person_id, other_person_id)
    candidate = DuplicateCandidate(person_a_id=person_a_id, person_b_id=person_b_id, reason=reason)
    db.add(candidate)
    db.flush()
    return candidate
