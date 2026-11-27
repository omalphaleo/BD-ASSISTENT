"""Tests for the real ingest_row in app.leads.ingest (M2-B4).

Needed because ingest_row is the one function both an import and a quarantine release run, so
every outcome and rule must hold on a real PostgreSQL: new rows import, invalid rows are
quarantined (D-068, D-069), the same person is updated and not duplicated (D-077), an uncertain
match becomes a possible duplicate (D-092), engagement history is applied (D-073), changes are
summarized (D-050), a failing row is rejected without half-written data, and nothing is ever
committed. Each test builds its own synthetic file, raw row and report.
"""

from datetime import UTC, datetime

import pytest
from factories.imports import make_import_file, make_import_report, make_raw_row
from factories.leads import make_company, make_person, make_person_email
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.compliance.models import OptOut
from app.imports.models import ImportChange, ImportFile, RawRow
from app.leads import ingest
from app.leads.contracts import ImportContext, IngestSource, RowOutcomeKind, SourceRow
from app.leads.ingest import REJECTED_REASON, ingest_row
from app.leads.models import (
    Company,
    DuplicateCandidate,
    EmailType,
    LeadEvent,
    Person,
    PersonEmail,
    QuarantineRecord,
)

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
BASE = {"first_name": "Jane", "last_name": "Doe", "email": "jane.doe@acme.example"}


def _source(
    session: Session,
    values: dict[str, object],
    *,
    import_file: ImportFile | None = None,
    with_report: bool = True,
    source: IngestSource = IngestSource.IMPORT,
) -> tuple[SourceRow, ImportContext]:
    """A mapped row stored as a raw row of a file (with a report), plus its context."""
    import_file = import_file or make_import_file(session)
    if with_report:
        make_import_report(session, import_file=import_file)
    raw_row = make_raw_row(session, import_file=import_file)
    row = SourceRow(
        row_number=raw_row.row_number,
        values=values,  # type: ignore[arg-type]
        raw_email=str(values.get("email")) if values.get("email") else None,
        import_file_id=import_file.id,
        source_profile_id=None,
        default_country="United States",
    )
    ctx = ImportContext(
        import_file_id=import_file.id,
        uploaded_by=None,
        now=NOW,
        cooling_off_days=90,
        source=source,
    )
    return row, ctx


def _again(session: Session, import_file: ImportFile, values: dict[str, object]):  # noqa: ANN202
    """A second row of the same file (same report), for re-import tests."""
    raw_row = make_raw_row(session, import_file=import_file)
    row = SourceRow(
        row_number=raw_row.row_number,
        values=values,  # type: ignore[arg-type]
        raw_email=None,
        import_file_id=import_file.id,
        source_profile_id=None,
        default_country=None,
    )
    ctx = ImportContext(
        import_file_id=import_file.id,
        uploaded_by=None,
        now=NOW,
        cooling_off_days=90,
        source=IngestSource.IMPORT,
    )
    return row, ctx


def _count(session: Session, model: type) -> int:
    """Number of rows of a model."""
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_new_valid_row_is_imported(db_session: Session) -> None:
    """A valid row creates the person, a primary work email, a company and links the raw row."""
    row, ctx = _source(db_session, {**BASE, "title": "CTO", "country": "usa", "state": "ca"})

    outcome = ingest_row(db_session, row, ctx)

    assert outcome.kind == RowOutcomeKind.IMPORTED
    person = db_session.get(Person, outcome.person_id)
    assert person is not None
    assert (person.first_name, person.last_name, person.title) == ("Jane", "Doe", "CTO")
    assert (person.country, person.state) == ("United States", "California")
    email = db_session.scalars(select(PersonEmail).where(PersonEmail.person_id == person.id)).one()
    assert email.normalized_address == "jane.doe@acme.example"
    assert email.is_primary
    assert email.type == EmailType.WORK
    raw_row = db_session.scalars(
        select(RawRow).where(RawRow.import_file_id == row.import_file_id)
    ).one()
    assert raw_row.person_id == person.id


def test_company_name_is_derived_and_industry_unknown_when_missing(db_session: Session) -> None:
    """No company name: derived from the email domain and flagged; no industry: "Unknown"."""
    row, ctx = _source(db_session, {**BASE, "email": "jane.doe@acme-corp.example"})

    outcome = ingest_row(db_session, row, ctx)

    person = db_session.get(Person, outcome.person_id)
    company = db_session.get(Company, person.company_id)  # type: ignore[union-attr]
    assert company is not None
    assert company.name == "Acme Corp"
    assert company.name_is_derived
    assert company.domain == "acme-corp.example"
    assert company.industry == "Unknown"


def test_company_columns_are_read_from_the_row(db_session: Session) -> None:
    """A given company name, industry, size and technologies are stored and normalized."""
    row, ctx = _source(
        db_session,
        {
            **BASE,
            "company_name": "Acme, Inc.",
            "industry": "Information Technology & Services",
            "employee_count": "1,200",
            "technologies": "Salesforce, AWS",
        },
    )

    outcome = ingest_row(db_session, row, ctx)

    person = db_session.get(Person, outcome.person_id)
    company = db_session.get(Company, person.company_id)  # type: ignore[union-attr]
    assert company is not None
    assert not company.name_is_derived
    assert company.normalized_name == "acme"
    assert company.employee_count == 1200
    assert company.technologies == ["Salesforce", "AWS"]
    assert company.uses_salesforce


def test_invalid_row_is_quarantined_not_imported(db_session: Session) -> None:
    """A personal-email-only row is parked with its reason; no person or company appears."""
    people_before = _count(db_session, Person)
    row, ctx = _source(db_session, {"first_name": "Jane", "email": "jane@gmail.com"})

    outcome = ingest_row(db_session, row, ctx)

    assert outcome.kind == RowOutcomeKind.QUARANTINED
    assert outcome.reason_code == "personal_email_only"
    assert outcome.person_id is None
    record = db_session.scalars(select(QuarantineRecord)).all()[-1]
    assert record.issues == ["personal_email_only"]
    assert _count(db_session, Person) == people_before


def test_row_without_first_name_is_quarantined(db_session: Session) -> None:
    """A work email but no first name: quarantined as missing_first_name (D-069)."""
    row, ctx = _source(db_session, {"email": "jane@acme.example"})

    outcome = ingest_row(db_session, row, ctx)

    assert outcome.kind == RowOutcomeKind.QUARANTINED
    assert outcome.reason_code == "missing_first_name"


def test_same_row_again_is_unchanged(db_session: Session) -> None:
    """Re-importing identical data finds the person by email, changes nothing, adds no summary."""
    first_row, ctx = _source(db_session, dict(BASE))
    created = ingest_row(db_session, first_row, ctx)
    import_file = db_session.get(ImportFile, ctx.import_file_id)
    row, ctx2 = _again(db_session, import_file, dict(BASE))  # type: ignore[arg-type]

    outcome = ingest_row(db_session, row, ctx2)

    assert outcome.kind == RowOutcomeKind.UNCHANGED
    assert outcome.person_id == created.person_id
    assert _count(db_session, ImportChange) == 0


def test_changed_value_updates_the_person_and_writes_the_summary(db_session: Session) -> None:
    """A newer title wins and ImportChange records {field, old, new} (D-050, D-046)."""
    first_row, ctx = _source(db_session, {**BASE, "title": "Engineer"})
    created = ingest_row(db_session, first_row, ctx)
    import_file = db_session.get(ImportFile, ctx.import_file_id)
    row, ctx2 = _again(db_session, import_file, {**BASE, "title": "CTO"})  # type: ignore[arg-type]

    outcome = ingest_row(db_session, row, ctx2)

    assert outcome.kind == RowOutcomeKind.UPDATED
    person = db_session.get(Person, created.person_id)
    assert person is not None
    assert person.title == "CTO"
    change = db_session.scalars(select(ImportChange)).one()
    assert change.person_id == person.id
    assert {"field": "title", "old": "Engineer", "new": "CTO"} in change.changes  # type: ignore[operator]


def test_blank_value_never_erases_stored_data(db_session: Session) -> None:
    """A re-import with an empty title keeps the stored title and reports UNCHANGED."""
    first_row, ctx = _source(db_session, {**BASE, "title": "Engineer"})
    created = ingest_row(db_session, first_row, ctx)
    import_file = db_session.get(ImportFile, ctx.import_file_id)
    row, ctx2 = _again(db_session, import_file, {**BASE, "title": "  "})  # type: ignore[arg-type]

    outcome = ingest_row(db_session, row, ctx2)

    assert outcome.kind == RowOutcomeKind.UNCHANGED
    person = db_session.get(Person, created.person_id)
    assert person is not None
    assert person.title == "Engineer"


def test_source_record_id_match_keeps_every_email(db_session: Session) -> None:
    """The same source id with a new address updates the person and keeps both addresses."""
    first_row, ctx = _source(db_session, {**BASE, "source_record_id": "apollo-9"})
    created = ingest_row(db_session, first_row, ctx)
    import_file = db_session.get(ImportFile, ctx.import_file_id)
    values = {
        **BASE,
        "email": "jane@acme.example",
        "secondary_email": "jane.doe@gmail.com",
        "source_record_id": "apollo-9",
    }
    row, ctx2 = _again(db_session, import_file, values)  # type: ignore[arg-type]

    outcome = ingest_row(db_session, row, ctx2)

    assert outcome.kind == RowOutcomeKind.UPDATED
    assert outcome.person_id == created.person_id
    emails = db_session.scalars(
        select(PersonEmail).where(PersonEmail.person_id == created.person_id)
    ).all()
    assert {e.normalized_address for e in emails} == {
        "jane.doe@acme.example",
        "jane@acme.example",
        "jane.doe@gmail.com",
    }
    assert sum(e.is_primary for e in emails) == 1
    assert {e.normalized_address: e.type for e in emails}[
        "jane.doe@gmail.com"
    ] == EmailType.PERSONAL


def test_same_name_and_domain_becomes_a_possible_duplicate(db_session: Session) -> None:
    """Different email, same name and company domain: a separate person plus an open pair."""
    company = make_company(db_session, domain="acme.example")
    existing = make_person(db_session, first_name="Jane", last_name="Doe", company_id=company.id)
    make_person_email(db_session, person=existing, normalized_address="old@acme.example")
    row, ctx = _source(db_session, dict(BASE))

    outcome = ingest_row(db_session, row, ctx)

    assert outcome.kind == RowOutcomeKind.POSSIBLE_DUPLICATE
    assert outcome.reason_code == "name_and_company_domain"
    assert outcome.person_id != existing.id
    pair = db_session.scalars(select(DuplicateCandidate)).one()
    assert {pair.person_a_id, pair.person_b_id} == {existing.id, outcome.person_id}
    assert db_session.get(Person, existing.id) is not None


def test_do_not_contact_row_is_imported_and_opted_out(db_session: Session) -> None:
    """Do-not-contact keeps the data valid but writes an opt-out for the address (D-073)."""
    row, ctx = _source(db_session, {**BASE, "do_not_contact": "Yes"})

    outcome = ingest_row(db_session, row, ctx)

    assert outcome.kind == RowOutcomeKind.IMPORTED
    opt_out = db_session.scalars(
        select(OptOut).where(OptOut.email_normalized == "jane.doe@acme.example")
    ).one()
    assert opt_out.removed_at is None


def test_bounced_replied_and_contacted_are_applied(db_session: Session) -> None:
    """A bounced status, a reply and a contact date set the person's engagement fields."""
    row, ctx = _source(
        db_session,
        {
            **BASE,
            "email_status": "Bounced",
            "replied": "true",
            "replied_at": "2026-11-01",
            "last_contacted_at": "2026-10-20T09:00:00+00:00",
        },
    )

    outcome = ingest_row(db_session, row, ctx)

    person = db_session.get(Person, outcome.person_id)
    assert person is not None
    assert person.email_bounced
    assert person.replied_at == datetime(2026, 11, 1, tzinfo=UTC)
    assert person.last_contacted_at == datetime(2026, 10, 20, 9, tzinfo=UTC)
    email = db_session.scalars(select(PersonEmail).where(PersonEmail.person_id == person.id)).one()
    assert email.is_invalid
    assert _count(db_session, LeadEvent) == 1


def test_derived_company_name_is_replaced_by_the_real_one(db_session: Session) -> None:
    """A later file that names the company replaces the derived name and reports the change."""
    first_row, ctx = _source(db_session, dict(BASE))
    created = ingest_row(db_session, first_row, ctx)
    import_file = db_session.get(ImportFile, ctx.import_file_id)
    row, ctx2 = _again(db_session, import_file, {**BASE, "company_name": "Acme Holdings"})  # type: ignore[arg-type]

    outcome = ingest_row(db_session, row, ctx2)

    assert outcome.kind == RowOutcomeKind.UPDATED
    person = db_session.get(Person, created.person_id)
    company = db_session.get(Company, person.company_id)  # type: ignore[union-attr]
    assert company is not None
    assert (company.name, company.name_is_derived) == ("Acme Holdings", False)
    change = db_session.scalars(select(ImportChange)).one()
    assert any(item["field"] == "company.name" for item in change.changes)  # type: ignore[union-attr]


def test_unexpected_failure_is_rejected_and_leaves_nothing(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An error after the person is created rolls the row back and reports REJECTED."""
    people_before = _count(db_session, Person)

    def boom(*args: object, **kwargs: object) -> None:
        """Fail like an unexpected bug late in the pipeline."""
        raise RuntimeError("boom")

    monkeypatch.setattr(ingest, "apply_engagement", boom)
    row, ctx = _source(db_session, dict(BASE))

    outcome = ingest_row(db_session, row, ctx)

    assert outcome.kind == RowOutcomeKind.REJECTED
    assert outcome.reason_code == REJECTED_REASON
    assert _count(db_session, Person) == people_before


def test_ingest_row_never_commits(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """The caller owns the transaction: ingest_row must not call commit."""

    def no_commit() -> None:
        """Fail the test if ingest_row commits."""
        raise AssertionError("ingest_row must not commit")

    monkeypatch.setattr(db_session, "commit", no_commit)
    row, ctx = _source(db_session, dict(BASE))

    assert ingest_row(db_session, row, ctx).kind == RowOutcomeKind.IMPORTED


def test_release_source_goes_through_the_same_pipeline(db_session: Session) -> None:
    """A quarantine-release call imports a valid row exactly like an import does."""
    row, ctx = _source(db_session, dict(BASE), source=IngestSource.QUARANTINE_RELEASE)

    outcome = ingest_row(db_session, row, ctx)

    assert outcome.kind == RowOutcomeKind.IMPORTED
    assert outcome.person_id is not None


def test_missing_report_still_updates_without_a_summary(db_session: Session) -> None:
    """With no ImportReport yet the update succeeds and simply writes no ImportChange."""
    first_row, ctx = _source(db_session, {**BASE, "title": "A"}, with_report=False)
    ingest_row(db_session, first_row, ctx)
    import_file = db_session.get(ImportFile, ctx.import_file_id)
    row, ctx2 = _again(db_session, import_file, {**BASE, "title": "B"})  # type: ignore[arg-type]

    assert ingest_row(db_session, row, ctx2).kind == RowOutcomeKind.UPDATED
    assert _count(db_session, ImportChange) == 0
