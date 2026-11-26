"""Tests for person and company matching in app.leads.matching (M2-B3).

Needed because matching decides whether a re-import updates a person or duplicates them
(D-077): each clue must find the right person in order, name plus company domain must only be
a POSSIBLE match (D-092), companies must not be merged on a name that visibly disagrees, and
a "not a duplicate" decision must be remembered. One test per path and rule. Synthetic data.
"""

from datetime import UTC, datetime

import pytest
from factories.leads import (
    make_company,
    make_duplicate_candidate,
    make_person,
    make_person_email,
)
from sqlalchemy.orm import Session

from app.leads.matching import (
    CompanyKeys,
    CompanyMatchRule,
    MatchStrength,
    PersonKeys,
    PersonMatchRule,
    find_company,
    find_person,
    is_marked_not_duplicate,
    record_possible_duplicate,
)
from app.leads.models import DuplicateStatus
from app.leads.normalization import normalize_company_name, normalize_linkedin_url

DECIDED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def test_person_source_record_id_is_certain(db_session: Session) -> None:
    """The source id finds the person for certain, before any other clue."""
    person = make_person(db_session, source_record_id="apollo-1")

    match = find_person(db_session, PersonKeys(source_record_id="apollo-1"))

    assert match.strength == MatchStrength.CERTAIN
    assert match.person_id == person.id
    assert match.rule == PersonMatchRule.SOURCE_RECORD_ID


def test_person_email_is_certain(db_session: Session) -> None:
    """A stored normalized address finds the person, including a secondary address."""
    person = make_person(db_session)
    make_person_email(db_session, person=person, normalized_address="jane@acme.example")
    make_person_email(db_session, person=person, normalized_address="j.doe@acme.example")

    match = find_person(db_session, PersonKeys(emails=("nobody@x.example", "j.doe@acme.example")))

    assert match.strength == MatchStrength.CERTAIN
    assert match.person_id == person.id
    assert match.rule == PersonMatchRule.EMAIL


def test_person_linkedin_url_is_certain(db_session: Session) -> None:
    """Decorated link text still matches the stored normalized LinkedIn link."""
    person = make_person(db_session, linkedin_url="linkedin.com/in/jane-doe")
    link = normalize_linkedin_url("https://www.LinkedIn.com/in/Jane-Doe/?a=1")

    match = find_person(db_session, PersonKeys(linkedin_url=link))

    assert match.strength == MatchStrength.CERTAIN
    assert match.person_id == person.id
    assert match.rule == PersonMatchRule.LINKEDIN_URL


def test_person_name_and_domain_is_only_possible(db_session: Session) -> None:
    """Same first name, last name and company domain: POSSIBLE, never certain (D-092)."""
    company = make_company(db_session, domain="acme.example")
    person = make_person(db_session, first_name="Jane", last_name="Doe", company_id=company.id)

    match = find_person(
        db_session,
        PersonKeys(first_name="JANE", last_name="doe", company_domain="acme.example"),
    )

    assert match.strength == MatchStrength.POSSIBLE
    assert match.person_id == person.id
    assert match.rule == PersonMatchRule.NAME_AND_COMPANY_DOMAIN


def test_person_name_and_domain_needs_both_names(db_session: Session) -> None:
    """A first name alone at one company is too weak a clue: no match."""
    company = make_company(db_session, domain="acme.example")
    make_person(db_session, first_name="Jane", last_name="Doe", company_id=company.id)

    match = find_person(db_session, PersonKeys(first_name="Jane", company_domain="acme.example"))

    assert match.strength == MatchStrength.NONE


def test_person_different_domain_is_no_match(db_session: Session) -> None:
    """Same name at another company is a different person."""
    company = make_company(db_session, domain="acme.example")
    make_person(db_session, first_name="Jane", last_name="Doe", company_id=company.id)

    match = find_person(
        db_session,
        PersonKeys(first_name="Jane", last_name="Doe", company_domain="other.example"),
    )

    assert match.strength == MatchStrength.NONE
    assert match.person_id is None


def test_person_clue_order_prefers_the_stronger_clue(db_session: Session) -> None:
    """When the source id and the email point at different people, the source id wins."""
    by_id = make_person(db_session, source_record_id="apollo-2")
    by_email = make_person(db_session)
    make_person_email(db_session, person=by_email, normalized_address="x@acme.example")

    match = find_person(
        db_session, PersonKeys(source_record_id="apollo-2", emails=("x@acme.example",))
    )

    assert match.person_id == by_id.id
    assert match.rule == PersonMatchRule.SOURCE_RECORD_ID


def test_person_with_no_clues_is_no_match(db_session: Session) -> None:
    """A row with no usable clue is a new person."""
    make_person(db_session)

    assert find_person(db_session, PersonKeys()).strength == MatchStrength.NONE


def test_company_apollo_account_id_matches_first(db_session: Session) -> None:
    """The Apollo Account ID beats a domain that points at another company."""
    by_id = make_company(db_session, apollo_account_id="acct-1")
    make_company(db_session, domain="acme.example")

    match = find_company(db_session, CompanyKeys(apollo_account_id="acct-1", domain="acme.example"))

    assert match.company_id == by_id.id
    assert match.rule == CompanyMatchRule.APOLLO_ACCOUNT_ID


def test_company_domain_matches(db_session: Session) -> None:
    """The domain finds the company when there is no Apollo Account ID."""
    company = make_company(db_session, domain="acme.example")

    match = find_company(db_session, CompanyKeys(domain="acme.example"))

    assert match.company_id == company.id
    assert match.rule == CompanyMatchRule.DOMAIN


def test_company_name_matches_when_nothing_disagrees(db_session: Session) -> None:
    """The normalized name finds a company that has no domain to disagree with."""
    company = make_company(db_session, domain=None, normalized_name="acme")

    match = find_company(db_session, CompanyKeys(domain="acme.example", normalized_name="acme"))

    assert match.company_id == company.id
    assert match.rule == CompanyMatchRule.NORMALIZED_NAME


def test_company_name_does_not_match_a_different_domain(db_session: Session) -> None:
    """Same name but a different domain: two firms, so no match."""
    make_company(db_session, domain="acme.example", normalized_name="acme")

    match = find_company(db_session, CompanyKeys(domain="acme.other", normalized_name="acme"))

    assert match.company_id is None


def test_company_name_does_not_match_a_different_apollo_id(db_session: Session) -> None:
    """Same name but a different Apollo Account ID: two firms, so no match."""
    make_company(db_session, domain=None, apollo_account_id="acct-1", normalized_name="acme")

    match = find_company(
        db_session, CompanyKeys(apollo_account_id="acct-2", normalized_name="acme")
    )

    assert match.company_id is None


def test_company_with_no_clues_is_no_match(db_session: Session) -> None:
    """A row with no company clue finds no company."""
    make_company(db_session)

    assert find_company(db_session, CompanyKeys()).company_id is None


def test_record_possible_duplicate_stores_the_pair_ordered(db_session: Session) -> None:
    """The pair is stored once, smallest id first, whichever order it is given in."""
    first, second = make_person(db_session), make_person(db_session)
    larger, smaller = sorted((first.id, second.id), reverse=True)

    candidate = record_possible_duplicate(db_session, larger, smaller)

    assert candidate is not None
    assert candidate.person_a_id == smaller
    assert candidate.person_b_id == larger
    assert candidate.status == DuplicateStatus.OPEN
    assert candidate.reason == "name_and_company_domain"


def test_record_possible_duplicate_is_not_raised_twice(db_session: Session) -> None:
    """Raising the same pair again, in either order, adds nothing."""
    first, second = make_person(db_session), make_person(db_session)
    assert record_possible_duplicate(db_session, first.id, second.id) is not None

    assert record_possible_duplicate(db_session, second.id, first.id) is None


def test_not_a_duplicate_decision_is_remembered(db_session: Session) -> None:
    """A pair a manager marked "not a duplicate" is never reopened by a later import."""
    pair = make_duplicate_candidate(
        db_session, status=DuplicateStatus.NOT_DUPLICATE, decided_at=DECIDED_AT
    )

    assert is_marked_not_duplicate(db_session, pair.person_b_id, pair.person_a_id)
    assert record_possible_duplicate(db_session, pair.person_a_id, pair.person_b_id) is None


def test_open_pair_is_not_marked_not_duplicate(db_session: Session) -> None:
    """An undecided pair is not treated as "not a duplicate"."""
    pair = make_duplicate_candidate(db_session)

    assert not is_marked_not_duplicate(db_session, pair.person_a_id, pair.person_b_id)


def test_record_possible_duplicate_ignores_the_same_person(db_session: Session) -> None:
    """A person cannot be a duplicate of themselves."""
    person = make_person(db_session)

    assert record_possible_duplicate(db_session, person.id, person.id) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.LinkedIn.com/in/Jane-Doe/?utm=x", "linkedin.com/in/jane-doe"),
        ("linkedin.com/in/jane-doe/", "linkedin.com/in/jane-doe"),
        ("  ", None),
        (None, None),
    ],
)
def test_normalize_linkedin_url(raw: str | None, expected: str | None) -> None:
    """Scheme, www, query, case and trailing slash are removed; blanks become None."""
    assert normalize_linkedin_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Acme, Inc.", "acme"),
        ("ACME LLC", "acme"),
        ("Johnson & Johnson", "johnson and johnson"),
        ("Inc", "inc"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_company_name(raw: str | None, expected: str | None) -> None:
    """Case, punctuation and a trailing legal form are removed; a lone suffix stays."""
    assert normalize_company_name(raw) == expected
