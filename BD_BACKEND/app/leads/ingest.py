"""The real ingest_row: one import row in, one outcome out (M2-B4, m2.md section 18).

Needed because this is the single function both entry points share: the import pipeline calls
it once per row (wired in imports/wiring.py by M2-A7) and quarantine release calls it for a
fixed row, so a released row is treated exactly like a new one. It joins the other W2 parts:
normalization and validation (B1), quarantine (B2), matching and engagement (B3) and merge
(B4). It never commits (the caller owns the transaction) and never raises: a row that fails
unexpectedly is rolled back to a savepoint and reported as REJECTED, so one bad row cannot
fail a file (D-068). Only imports/wiring.py may import this module from the imports side
(tests/test_module_dependencies.py).
"""

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.imports.models import RawRow
from app.leads.contracts import (
    FieldChange,
    ImportContext,
    RowOutcome,
    RowOutcomeKind,
    SourceRow,
)
from app.leads.engagement import apply_engagement
from app.leads.matching import (
    CompanyKeys,
    MatchStrength,
    PersonKeys,
    find_company,
    find_person,
    record_possible_duplicate,
)
from app.leads.merge import (
    IncomingEmail,
    merge_attributes,
    merge_emails,
    record_import_change,
)
from app.leads.models import Company, EmailType, Person
from app.leads.normalization import (
    EmailKind,
    classify_email,
    derive_company_name,
    email_domain,
    is_valid_email_format,
    normalize_company_name,
    normalize_email_address,
)
from app.leads.quarantine import quarantine_row
from app.leads.reference_data import UNKNOWN_INDUSTRY
from app.leads.row_fields import ParsedRow, parse_row
from app.leads.validation import ValidationResult, validate_row

logger = logging.getLogger(__name__)

REJECTED_REASON = "unexpected_error"
VERIFIED_STATUS = "verified"
_EMAIL_TYPE_BY_KIND = {
    EmailKind.WORK: EmailType.WORK,
    EmailKind.PERSONAL: EmailType.PERSONAL,
    EmailKind.GENERIC: EmailType.GENERIC,
}


def _incoming_emails(parsed: ParsedRow, validation: ValidationResult) -> list[IncomingEmail]:
    """Classify every usable address of the row; the validated work email is the main one.

    Badly formed addresses are dropped (they cannot be mailed); personal, generic and
    secondary addresses are kept for the record but never used for outreach (D-072).
    """
    verified = (parsed.email_status or "").lower() == VERIFIED_STATUS
    emails: list[IncomingEmail] = []
    seen: set[str] = set()
    for cell in parsed.email_cells:
        normalized = normalize_email_address(cell)
        if normalized is None or normalized in seen or not is_valid_email_format(normalized):
            continue
        seen.add(normalized)
        is_main = normalized == validation.work_email
        emails.append(
            IncomingEmail(
                address=(cell or normalized).strip(),
                normalized_address=normalized,
                type=_EMAIL_TYPE_BY_KIND[classify_email(normalized)],
                verified=is_main and verified,
                is_main=is_main,
            )
        )
    return emails


def _resolve_company(
    session: Session, parsed: ParsedRow, work_email: str
) -> tuple[Company, list[FieldChange]]:
    """Find the row's company or create it; return it with the changes made to an existing one.

    Domain: the work-email domain first, the website as fallback (D-077). A name missing from
    the file is derived from the work-email domain and marked as derived (D-071); a derived
    name is replaced as soon as a file supplies the real one. A missing industry becomes
    "Unknown" on create (D-070).
    """
    domain = email_domain(work_email) or parsed.website_domain
    file_name = parsed.company_name
    name = file_name or derive_company_name(work_email) or domain or work_email
    normalized_name = normalize_company_name(name)
    match = find_company(
        session,
        CompanyKeys(
            apollo_account_id=parsed.company.get("apollo_account_id"),  # type: ignore[arg-type]
            domain=domain,
            normalized_name=normalized_name,
        ),
    )
    if match.company_id is None:
        company = Company(
            **{
                "industry": UNKNOWN_INDUSTRY,
                **parsed.company,
                "name": name,
                "normalized_name": normalized_name or name.lower(),
                "name_is_derived": file_name is None,
                "domain": domain,
            }
        )
        session.add(company)
        session.flush()
        return company, []

    company = session.get(Company, match.company_id)
    assert company is not None  # the id was just read from the same session
    incoming: dict[str, object] = dict(parsed.company)
    if company.domain is None and domain is not None:
        incoming["domain"] = domain
    changes: list[FieldChange] = []
    if file_name is not None and company.name_is_derived:
        incoming.update(name=file_name, normalized_name=normalized_name, name_is_derived=False)
    changes.extend(merge_attributes(company, incoming, prefix="company."))
    return company, changes


def _link_raw_row(session: Session, row: SourceRow, person: Person) -> None:
    """Point the stored raw row at the person; person_id is the one column allowed to change."""
    raw_row = session.execute(
        select(RawRow).where(
            RawRow.import_file_id == row.import_file_id, RawRow.row_number == row.row_number
        )
    ).scalar_one_or_none()
    if raw_row is not None:
        raw_row.person_id = person.id


def _ingest(session: Session, row: SourceRow, ctx: ImportContext) -> RowOutcome:
    """Run the whole pipeline for one row (see ingest_row); may raise on unexpected errors."""
    parsed = parse_row(row)
    validation = validate_row(parsed.first_name_cell, parsed.email_cells, parsed.email_status)
    if not validation.is_valid or validation.work_email is None or validation.first_name is None:
        quarantine_row(session, row, validation.issues)
        return RowOutcome(RowOutcomeKind.QUARANTINED, reason_code=validation.issues[0].value)

    emails = _incoming_emails(parsed, validation)
    company, company_changes = _resolve_company(session, parsed, validation.work_email)
    match = find_person(
        session,
        PersonKeys(
            source_record_id=parsed.person.get("source_record_id"),  # type: ignore[arg-type]
            emails=tuple(email.normalized_address for email in emails),
            linkedin_url=parsed.person.get("linkedin_url"),  # type: ignore[arg-type]
            first_name=validation.first_name,
            last_name=parsed.last_name,
            company_domain=company.domain,
        ),
    )

    if match.strength == MatchStrength.CERTAIN and match.person_id is not None:
        person = session.get(Person, match.person_id)
        assert person is not None  # the id was just read from the same session
        changes = _merge_person(session, person, parsed, validation, company, emails)
        changes.extend(company_changes)
        apply_engagement(session, person, parsed.engagement, ctx)
        record_import_change(session, ctx.import_file_id, person.id, changes)
        _link_raw_row(session, row, person)
        kind = RowOutcomeKind.UPDATED if changes else RowOutcomeKind.UNCHANGED
        return RowOutcome(kind, person_id=person.id)

    # New person. A possible match (same name at the same company domain) is not merged: the
    # row is imported as a separate record and flagged for a manager (D-092).
    person = Person(
        first_name=validation.first_name,
        last_name=parsed.last_name,
        company_id=company.id,
        **parsed.person,
    )
    session.add(person)
    session.flush()
    merge_emails(session, person, emails)
    apply_engagement(session, person, parsed.engagement, ctx)
    _link_raw_row(session, row, person)
    if match.strength == MatchStrength.POSSIBLE and match.person_id is not None:
        candidate = record_possible_duplicate(session, person.id, match.person_id)
        reason = candidate.reason if candidate else None
        return RowOutcome(
            RowOutcomeKind.POSSIBLE_DUPLICATE, reason_code=reason, person_id=person.id
        )
    return RowOutcome(RowOutcomeKind.IMPORTED, person_id=person.id)


def _merge_person(
    session: Session,
    person: Person,
    parsed: ParsedRow,
    validation: ValidationResult,
    company: Company,
    emails: Sequence[IncomingEmail],
) -> list[FieldChange]:
    """Merge a row into the matched person: latest wins, blanks never erase, emails are kept."""
    incoming: dict[str, object] = {
        "first_name": validation.first_name,
        "last_name": parsed.last_name,
        **parsed.person,
    }
    changes = merge_attributes(person, incoming)
    if person.company_id != company.id:
        old = session.get(Company, person.company_id) if person.company_id else None
        changes.append(FieldChange("company", old.name if old else None, company.name))
        person.company_id = company.id
    changes.extend(merge_emails(session, person, emails))
    return changes


def ingest_row(session: Session, row: SourceRow, ctx: ImportContext) -> RowOutcome:
    """Process one row and report what happened to it (the IngestRow contract).

    Steps: normalize and validate; an invalid row is parked in quarantine; a valid one is
    matched to an existing person (merged: UPDATED or UNCHANGED) or created (IMPORTED, or
    POSSIBLE_DUPLICATE when only name and company domain matched), then the source's
    engagement history is applied (D-073) and the changes are summarized (D-050).

    Everything for the row runs inside a savepoint, so an unexpected failure leaves no
    half-written row behind. The caller still owns the outer transaction: nothing is committed.

    Returns:
        The outcome. REJECTED with reason code "unexpected_error" when the row failed
        unexpectedly; the file carries on (D-068).
    """
    try:
        with session.begin_nested():
            return _ingest(session, row, ctx)
    except Exception as error:  # noqa: BLE001 - a bad row must never fail the whole file (D-068)
        # Log the error class and the position only: the message may contain lead values.
        logger.error(
            "ingest_row failed: import=%s row=%s error=%s",
            ctx.import_file_id,
            row.row_number,
            type(error).__name__,
        )
        return RowOutcome(RowOutcomeKind.REJECTED, reason_code=REJECTED_REASON)
