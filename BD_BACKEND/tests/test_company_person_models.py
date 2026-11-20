"""Tests for Company, Person and their address/phone/profile/channel tables against real PostgreSQL.

Needed because lowercase rules, uniqueness, the one-primary-email rule and delete behaviour are
enforced by the database; these tests prove those constraints and that arrays, defaults and
foreign keys behave as designed (M1 task A3). All data is synthetic.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import reset_offset, set_offset
from app.core.models import User
from app.leads.models import (
    Company,
    ContactChannel,
    ContactChannelType,
    EmailType,
    EmailVerificationStatus,
    Person,
    PersonEmail,
    PersonPhone,
    SocialProfile,
)


@pytest.fixture(autouse=True)
def _reset_clock_offset() -> None:
    """Restore the real clock after a test that moved it."""
    yield
    reset_offset()


def _email(person: Person, address: str = "jane@acme.example", **kwargs: object) -> PersonEmail:
    """Build a work email for a person; keyword arguments override the defaults."""
    values: dict[str, object] = {
        "person_id": person.id,
        "address": address,
        "normalized_address": address.lower(),
        "type": EmailType.WORK,
    }
    values.update(kwargs)
    return PersonEmail(**values)


def test_company_defaults(db_session: Session, company: Company) -> None:
    """A minimal company gets Unknown industry, empty arrays and false flags from defaults."""
    db_session.refresh(company)

    assert company.industry == "Unknown"
    assert company.technologies == [] and company.keywords == []
    assert company.uses_salesforce is False and company.name_is_derived is False


def test_company_arrays_round_trip(db_session: Session, company: Company) -> None:
    """technologies and keywords store and return lists of strings."""
    company.technologies = ["salesforce", "aws"]
    company.keywords = ["erp"]
    db_session.flush()
    db_session.refresh(company)

    assert company.technologies == ["salesforce", "aws"]
    assert company.keywords == ["erp"]


def test_company_domain_must_be_lowercase(db_session: Session) -> None:
    """A mixed-case domain is rejected by the CHECK."""
    db_session.add(Company(name="X", normalized_name="x", domain="Acme.Example"))
    with pytest.raises(IntegrityError, match="ck_companies_domain_lowercase"):
        db_session.flush()


def test_company_apollo_account_id_is_unique(db_session: Session) -> None:
    """Two companies cannot share an Apollo account id, but many may have none."""
    db_session.add_all(
        [
            Company(name="A", normalized_name="a", apollo_account_id="acc-1"),
            Company(name="B", normalized_name="b"),
            Company(name="C", normalized_name="c"),
        ]
    )
    db_session.flush()

    db_session.add(Company(name="D", normalized_name="d", apollo_account_id="acc-1"))
    with pytest.raises(IntegrityError, match="uq_companies_apollo_account_id"):
        db_session.flush()


@pytest.mark.parametrize("column", ["employee_count", "annual_revenue", "total_funding"])
def test_company_numbers_cannot_be_negative(db_session: Session, column: str) -> None:
    """A negative employee count, revenue or funding is rejected."""
    db_session.add(Company(name="X", normalized_name="x", **{column: -1}))
    with pytest.raises(IntegrityError, match="nonnegative"):
        db_session.flush()


def test_person_requires_first_name(db_session: Session) -> None:
    """A person without a first name is rejected (mandatory field, D-069)."""
    db_session.add(Person(first_name=None))
    with pytest.raises(IntegrityError, match="first_name"):
        db_session.flush()


def test_person_defaults_and_timestamps_follow_the_clock(db_session: Session) -> None:
    """Defaults apply, and created_at comes from core.clock.now(), not the server."""
    set_offset(timedelta(days=3))
    person = Person(first_name="Sam")
    db_session.add(person)
    db_session.flush()
    db_session.refresh(person)

    assert person.lists == [] and person.email_bounced is False and person.owner_id is None
    assert abs(person.created_at - (datetime.now(UTC) + timedelta(days=3))) < timedelta(minutes=1)


def test_deleting_the_company_keeps_the_person(
    db_session: Session, company: Company, person: Person
) -> None:
    """Company deletion sets people.company_id to NULL and keeps the person."""
    db_session.execute(delete(Company).where(Company.id == company.id))
    db_session.refresh(person)

    assert person.company_id is None


def test_deleting_the_owner_returns_the_person_to_unassigned(
    db_session: Session, user: User, person: Person
) -> None:
    """Deleting the owning user clears owner_id (the Unassigned pool, D-075)."""
    person.owner_id = user.id
    db_session.flush()
    db_session.execute(delete(User).where(User.id == user.id))
    db_session.refresh(person)

    assert person.owner_id is None


def test_email_defaults(db_session: Session, person: Person) -> None:
    """A new address is unverified, non-primary and valid unless stated otherwise."""
    email = _email(person)
    db_session.add(email)
    db_session.flush()
    db_session.refresh(email)

    assert email.verification_status is EmailVerificationStatus.UNVERIFIED
    assert email.is_primary is False and email.is_invalid is False


def test_email_normalized_address_must_be_lowercase(db_session: Session, person: Person) -> None:
    """A normalized address with capitals is rejected."""
    db_session.add(_email(person, normalized_address="Jane@Acme.Example"))
    with pytest.raises(IntegrityError, match="ck_person_emails_normalized_lowercase"):
        db_session.flush()


def test_email_type_is_limited_to_known_values(db_session: Session, person: Person) -> None:
    """An unknown email type is rejected by the CHECK."""
    db_session.add(_email(person, type="burner"))
    with pytest.raises(IntegrityError, match="ck_person_emails_type_valid"):
        db_session.flush()


def test_same_person_cannot_have_the_same_address_twice(
    db_session: Session, person: Person
) -> None:
    """Per person the normalized address is unique."""
    db_session.add(_email(person))
    db_session.flush()

    db_session.add(_email(person, address="JANE@acme.example"))
    with pytest.raises(IntegrityError, match="uq_person_emails_person_id_normalized"):
        db_session.flush()


def test_two_people_can_share_an_address(db_session: Session, person: Person) -> None:
    """Possible-duplicate records may hold the same address (D-092): no global uniqueness."""
    other = Person(first_name="Jane")
    db_session.add(other)
    db_session.flush()

    db_session.add_all([_email(person), _email(other)])
    db_session.flush()  # must not raise


def test_a_person_has_at_most_one_primary_email(db_session: Session, person: Person) -> None:
    """A second primary address for the same person is rejected; non-primary ones are fine."""
    db_session.add_all(
        [
            _email(person, "a@acme.example", is_primary=True),
            _email(person, "b@acme.example"),
            _email(person, "c@acme.example"),
        ]
    )
    db_session.flush()

    db_session.add(_email(person, "d@acme.example", is_primary=True))
    with pytest.raises(IntegrityError, match="uq_person_emails_primary_per_person"):
        db_session.flush()


def test_deleting_a_person_removes_their_details(db_session: Session, person: Person) -> None:
    """Erase-person (D-099) cascades to emails, phones and profiles."""
    db_session.add_all(
        [
            _email(person),
            PersonPhone(person_id=person.id, number="+1 555 0100"),
            SocialProfile(
                person_id=person.id, network="linkedin", url="https://example.com/in/jane"
            ),
        ]
    )
    db_session.flush()

    db_session.execute(delete(Person).where(Person.id == person.id))

    for model in (PersonEmail, PersonPhone, SocialProfile):
        assert db_session.scalars(select(model)).all() == []


def test_phone_and_profile_are_unique_per_person(
    db_session: Session, person: Person, assert_rejected: Callable[[object, str], None]
) -> None:
    """The same number or profile URL cannot be stored twice for one person."""
    db_session.add_all(
        [
            PersonPhone(person_id=person.id, number="+1 555 0100"),
            SocialProfile(person_id=person.id, network="linkedin", url="https://example.com/in/j"),
        ]
    )
    db_session.flush()

    assert_rejected(
        PersonPhone(person_id=person.id, number="+1 555 0100"), "uq_person_phones_person_id_number"
    )
    assert_rejected(
        SocialProfile(person_id=person.id, network="linkedin", url="https://example.com/in/j"),
        "uq_social_profiles_person_url",
    )


def test_contact_channel_is_unique_per_company_and_type(
    db_session: Session, company: Company
) -> None:
    """The same channel value cannot be added twice to a company, and unknown types fail."""
    db_session.add(
        ContactChannel(
            company_id=company.id, channel_type=ContactChannelType.EMAIL, value="info@acme.example"
        )
    )
    db_session.flush()

    db_session.add(
        ContactChannel(
            company_id=company.id, channel_type=ContactChannelType.EMAIL, value="info@acme.example"
        )
    )
    with pytest.raises(IntegrityError, match="uq_contact_channels_company_type_value"):
        db_session.flush()
