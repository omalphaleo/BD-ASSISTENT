"""Tests for the merge rules in app.leads.merge (M2-B4, D-046, D-050, D-072).

Needed because merge is where stored lead data could be damaged: the latest value must win,
a blank must never erase, every address must be kept and an existing primary must stay, and
the ImportChange summary must hold {field, old, new} per changed field. One test per rule.
"""

from decimal import Decimal

from factories.imports import make_import_file, make_import_report
from factories.leads import make_company, make_person, make_person_email
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.imports.models import ImportChange
from app.leads.contracts import FieldChange
from app.leads.merge import (
    EMAILS_FIELD,
    IncomingEmail,
    merge_attributes,
    merge_emails,
    record_import_change,
)
from app.leads.models import EmailType, PersonEmail


def test_latest_value_wins_and_is_reported(db_session: Session) -> None:
    """A different incoming value replaces the stored one and reports old and new."""
    person = make_person(db_session, title="Engineer")

    changes = merge_attributes(person, {"title": "CTO"})

    assert person.title == "CTO"
    assert changes == [FieldChange("title", "Engineer", "CTO")]


def test_equal_value_reports_nothing(db_session: Session) -> None:
    """The same value is not a change."""
    person = make_person(db_session, title="CTO")

    assert merge_attributes(person, {"title": "CTO"}) == []


def test_blank_value_never_erases(db_session: Session) -> None:
    """None, blank text and an empty list leave the stored values untouched."""
    company = make_company(db_session, hq_city="Austin", technologies=["AWS"])

    changes = merge_attributes(company, {"hq_city": "  ", "technologies": [], "sic": None})

    assert changes == []
    assert (company.hq_city, company.technologies) == ("Austin", ["AWS"])


def test_unknown_attribute_is_ignored(db_session: Session) -> None:
    """A name the record does not have is skipped, not an error."""
    person = make_person(db_session)

    assert merge_attributes(person, {"no_such_column": "x"}) == []


def test_prefix_and_decimal_values_are_reported_as_json(db_session: Session) -> None:
    """The prefix marks company fields; Decimal values are reported as text."""
    company = make_company(db_session, annual_revenue=Decimal("100"))

    changes = merge_attributes(company, {"annual_revenue": Decimal("250.5")}, prefix="company.")

    assert changes == [FieldChange("company.annual_revenue", "100", "250.5")]


def test_new_addresses_are_added_and_known_ones_skipped(db_session: Session) -> None:
    """Only addresses the person lacks are added; none is removed or duplicated."""
    person = make_person(db_session)
    make_person_email(
        db_session, person=person, normalized_address="a@acme.example", is_primary=True
    )
    incoming = [
        IncomingEmail("A@acme.example", "a@acme.example", EmailType.WORK, is_main=True),
        IncomingEmail("b@gmail.com", "b@gmail.com", EmailType.PERSONAL),
    ]

    changes = merge_emails(db_session, person, incoming)

    assert changes == [FieldChange(EMAILS_FIELD, None, "b@gmail.com")]
    stored = db_session.scalars(select(PersonEmail).where(PersonEmail.person_id == person.id)).all()
    assert {e.normalized_address for e in stored} == {"a@acme.example", "b@gmail.com"}


def test_existing_primary_is_never_replaced(db_session: Session) -> None:
    """A new main address does not take over primary from an existing one."""
    person = make_person(db_session)
    old = make_person_email(
        db_session, person=person, normalized_address="old@acme.example", is_primary=True
    )
    incoming = [IncomingEmail("new@acme.example", "new@acme.example", EmailType.WORK, is_main=True)]

    merge_emails(db_session, person, incoming)

    new = db_session.scalars(
        select(PersonEmail).where(PersonEmail.normalized_address == "new@acme.example")
    ).one()
    assert old.is_primary
    assert not new.is_primary


def test_first_main_address_becomes_primary(db_session: Session) -> None:
    """With no primary yet, the main work address becomes primary."""
    person = make_person(db_session)

    merge_emails(
        db_session,
        person,
        [IncomingEmail("n@acme.example", "n@acme.example", EmailType.WORK, is_main=True)],
    )

    email = db_session.scalars(select(PersonEmail).where(PersonEmail.person_id == person.id)).one()
    assert email.is_primary


def _report_for(session: Session):  # noqa: ANN202
    """A file with its report, returned as (file id, report)."""
    import_file = make_import_file(session)
    return import_file.id, make_import_report(session, import_file=import_file)


def test_import_change_row_holds_field_old_new(db_session: Session) -> None:
    """The summary row stores a list of {field, old, new} objects (D-050)."""
    file_id, report = _report_for(db_session)
    person = make_person(db_session)

    written = record_import_change(db_session, file_id, person.id, [FieldChange("title", "A", "B")])

    assert written
    row = db_session.scalars(
        select(ImportChange).where(ImportChange.import_report_id == report.id)
    ).one()
    assert row.changes == [{"field": "title", "old": "A", "new": "B"}]


def test_second_update_keeps_first_old_and_latest_new(db_session: Session) -> None:
    """Two rows of one import changing a field give one entry: first old, latest new."""
    file_id, report = _report_for(db_session)
    person = make_person(db_session)
    record_import_change(db_session, file_id, person.id, [FieldChange("title", "A", "B")])

    record_import_change(
        db_session,
        file_id,
        person.id,
        [FieldChange("title", "B", "C"), FieldChange(EMAILS_FIELD, None, "x@acme.example")],
    )

    row = db_session.scalars(
        select(ImportChange).where(ImportChange.import_report_id == report.id)
    ).one()
    assert {"field": "title", "old": "A", "new": "C"} in row.changes  # type: ignore[operator]
    assert {"field": EMAILS_FIELD, "old": None, "new": "x@acme.example"} in row.changes  # type: ignore[operator]
    assert len(row.changes) == 2  # type: ignore[arg-type]


def test_no_changes_or_no_report_writes_nothing(db_session: Session) -> None:
    """An empty change list, or a file without a report, writes no row."""
    file_id, _ = _report_for(db_session)
    person = make_person(db_session)

    assert not record_import_change(db_session, file_id, person.id, [])
    no_report_file = make_import_file(db_session)
    assert not record_import_change(
        db_session, no_report_file.id, person.id, [FieldChange("title", "A", "B")]
    )
