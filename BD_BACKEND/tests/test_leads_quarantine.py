"""Tests for the quarantine service in app.leads.quarantine on a real PostgreSQL (M2-B2).

Needed because quarantine is how a bad row stays fixable instead of lost (D-068): parking a
row once per raw row, listing and filtering, fixing with revalidation, releasing through
ingest_row, and discarding by the importer, a manager or an admin (D-107). Each rule has its
own test, including that audit events never carry lead values and the raw row never changes.
"""

import uuid
from datetime import UTC, datetime

import pytest
from factories.core import make_user
from factories.imports import make_import_file, make_raw_row
from factories.leads import make_person, make_quarantine_record
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.core.models import User, UserRole
from app.core.permissions import PermissionDeniedError
from app.imports.models import ImportFile, RawRow
from app.leads import quarantine
from app.leads.contracts import (
    ImportContext,
    IngestSource,
    RowOutcome,
    RowOutcomeKind,
    SourceRow,
)
from app.leads.models import QuarantineRecord, QuarantineStatus
from app.leads.quarantine import (
    IngestUnavailableError,
    QuarantineFieldError,
    QuarantineNotFoundError,
    QuarantineNotOpenError,
    QuarantineNotReleasableError,
)
from app.leads.validation import RowIssue

PERSONAL_PAYLOAD = {"first_name": "Jane", "email": "jane@gmail.com"}
VALID_PAYLOAD = {"first_name": "Jane", "email": "jane@acme.com"}


def _user(session: Session, role: UserRole) -> User:
    """A synthetic active user with the given role."""
    return make_user(session, role=role)


def _parked(
    session: Session,
    *,
    importer: User | None = None,
    payload: dict[str, object] | None = None,
    issues: list[str] | None = None,
) -> tuple[QuarantineRecord, RawRow, ImportFile]:
    """An open record linked to a raw row of a file uploaded by `importer`."""
    import_file = make_import_file(session, uploaded_by=importer.id if importer else None)
    raw_row = make_raw_row(session, import_file=import_file)
    record = make_quarantine_record(
        session,
        raw_row_id=raw_row.id,
        payload=payload if payload is not None else dict(PERSONAL_PAYLOAD),
        issues=issues if issues is not None else ["personal_email_only"],
    )
    return record, raw_row, import_file


class RecordingIngest:
    """Stands in for the real ingest_row (M2-B4): records its calls, returns a fixed outcome."""

    def __init__(self, outcome: RowOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[SourceRow, ImportContext]] = []

    def __call__(self, session: Session, row: SourceRow, ctx: ImportContext) -> RowOutcome:
        self.calls.append((row, ctx))
        return self.outcome


def _audit_actions(session: Session) -> list[str]:
    """Audit actions recorded so far, oldest first."""
    return [row.action for row in session.scalars(select(AuditLog).order_by(AuditLog.occurred_at))]


# --- quarantine_row ----------------------------------------------------------------------------


def _source_row(import_file: ImportFile, raw_row: RawRow, **values: object) -> SourceRow:
    """A SourceRow for an existing raw row."""
    return SourceRow(
        row_number=raw_row.row_number,
        values={"first_name": "Jane", **values},  # type: ignore[arg-type]
        raw_email=" Jane@Gmail.com ",
        import_file_id=import_file.id,
        source_profile_id=None,
        default_country=None,
    )


def test_quarantine_row_parks_the_row_linked_to_its_raw_row(db_session: Session) -> None:
    """An invalid row becomes an open record with its reasons, payload and raw-row link."""
    import_file = make_import_file(db_session)
    raw_row = make_raw_row(db_session, import_file=import_file)

    created = quarantine.quarantine_row(
        db_session, _source_row(import_file, raw_row), [RowIssue.PERSONAL_EMAIL_ONLY]
    )

    assert created.status == QuarantineStatus.OPEN
    assert created.issues == ["personal_email_only"]
    assert created.raw_row_id == raw_row.id
    # The email text is kept exactly as the file had it, so BD sees what was received.
    assert created.payload == {"first_name": "Jane", "email": " Jane@Gmail.com "}


def test_quarantine_row_twice_updates_instead_of_duplicating(db_session: Session) -> None:
    """Re-running the same row (worker crash, repeat release) refreshes the one record."""
    import_file = make_import_file(db_session)
    raw_row = make_raw_row(db_session, import_file=import_file)
    row = _source_row(import_file, raw_row)

    first = quarantine.quarantine_row(db_session, row, [RowIssue.PERSONAL_EMAIL_ONLY])
    second = quarantine.quarantine_row(
        db_session, row, [RowIssue.PERSONAL_EMAIL_ONLY, RowIssue.MISSING_FIRST_NAME]
    )

    assert second.id == first.id
    assert second.issues == ["personal_email_only", "missing_first_name"]
    assert db_session.scalars(select(QuarantineRecord)).all() == [first]


def test_quarantine_row_leaves_a_resolved_record_alone(db_session: Session) -> None:
    """A record that was already discarded is not reopened by a later parking call."""
    import_file = make_import_file(db_session)
    raw_row = make_raw_row(db_session, import_file=import_file)
    parked = quarantine.quarantine_row(
        db_session, _source_row(import_file, raw_row), [RowIssue.PERSONAL_EMAIL_ONLY]
    )
    parked.status = QuarantineStatus.DISCARDED
    parked.resolved_at = datetime(2026, 11, 26, tzinfo=UTC)
    db_session.flush()

    again = quarantine.quarantine_row(
        db_session, _source_row(import_file, raw_row), [RowIssue.BAD_EMAIL_FORMAT]
    )

    assert again.status == QuarantineStatus.DISCARDED
    assert again.issues == ["personal_email_only"]


def test_quarantine_row_without_issues_is_refused(db_session: Session) -> None:
    """A valid row must not be quarantined: an empty reason list raises ValueError."""
    import_file = make_import_file(db_session)
    raw_row = make_raw_row(db_session, import_file=import_file)

    with pytest.raises(ValueError):
        quarantine.quarantine_row(db_session, _source_row(import_file, raw_row), [])


# --- list and get ------------------------------------------------------------------------------


def test_list_defaults_to_open_and_filters_by_status_and_issue(db_session: Session) -> None:
    """The list shows open records by default; status and reason filters narrow it."""
    importer = _user(db_session, UserRole.REP)
    open_personal, _, _ = _parked(db_session, importer=importer)
    open_generic, _, _ = _parked(db_session, importer=importer, issues=["generic_email_only"])
    discarded, _, _ = _parked(db_session, importer=importer)
    discarded.status = QuarantineStatus.DISCARDED
    discarded.resolved_at = datetime(2026, 11, 26, tzinfo=UTC)
    db_session.flush()

    open_items, open_total = quarantine.list_items(db_session)
    generic_items, _ = quarantine.list_items(db_session, issue=RowIssue.GENERIC_EMAIL_ONLY)
    all_items, all_total = quarantine.list_items(db_session, status=None)

    assert {item.record.id for item in open_items} == {open_personal.id, open_generic.id}
    assert open_total == 2
    assert [item.record.id for item in generic_items] == [open_generic.id]
    assert all_total == 3
    assert len(all_items) == 3


def test_list_pages_and_reports_the_total(db_session: Session) -> None:
    """limit and offset page the results while total still counts every match."""
    for _ in range(3):
        _parked(db_session)

    page, total = quarantine.list_items(db_session, limit=2, offset=0)
    rest, _ = quarantine.list_items(db_session, limit=2, offset=2)

    assert total == 3
    assert len(page) == 2
    assert len(rest) == 1
    assert {item.record.id for item in page}.isdisjoint({item.record.id for item in rest})


def test_item_carries_the_source_file_and_row(db_session: Session) -> None:
    """Each item says which file, row number and importer the record came from."""
    importer = _user(db_session, UserRole.REP)
    record, raw_row, import_file = _parked(db_session, importer=importer)

    item = quarantine.get_item(db_session, record.id)

    assert item.import_file_id == import_file.id
    assert item.filename == import_file.filename
    assert item.row_number == raw_row.row_number
    assert item.uploaded_by == importer.id


def test_get_unknown_record_raises(db_session: Session) -> None:
    """An id that does not exist raises QuarantineNotFoundError."""
    with pytest.raises(QuarantineNotFoundError):
        quarantine.get_item(db_session, uuid.uuid4())


# --- fix ---------------------------------------------------------------------------------------


def test_fix_adding_a_work_email_clears_the_issues_and_audits(db_session: Session) -> None:
    """Adding a work email empties the reasons, is audited, and leaves the raw row untouched."""
    rep = _user(db_session, UserRole.REP)
    record, raw_row, _ = _parked(db_session, importer=rep)
    original_values = dict(raw_row.original_values)

    quarantine.fix_item(db_session, rep, record.id, {"email": "jane@acme.com"})

    assert record.payload == {"first_name": "Jane", "email": "jane@acme.com"}
    assert record.issues == []
    assert record.status == QuarantineStatus.OPEN
    assert raw_row.original_values == original_values
    assert _audit_actions(db_session) == ["quarantine.fixed"]


def test_fix_refreshes_reasons_that_are_still_wrong(db_session: Session) -> None:
    """A fix that does not solve the problem updates the reasons to what is still wrong."""
    rep = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=rep)

    quarantine.fix_item(db_session, rep, record.id, {"email": "info@acme.com", "first_name": ""})

    assert record.issues == ["generic_email_only", "missing_first_name"]


def test_fix_by_any_bd_user_not_only_the_importer(db_session: Session) -> None:
    """Any BD user may fix a row, including one imported by someone else (D-107)."""
    importer = _user(db_session, UserRole.REP)
    other_rep = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=importer)

    quarantine.fix_item(db_session, other_rep, record.id, {"email": "jane@acme.com"})

    assert record.issues == []


def test_audit_summaries_hold_field_names_but_no_lead_values(db_session: Session) -> None:
    """The permanent audit log records which fields changed, never the email or name values."""
    rep = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=rep)

    quarantine.fix_item(db_session, rep, record.id, {"email": "secret.person@acme.com"})
    audit = db_session.scalars(select(AuditLog)).one()

    assert audit.summary == {
        "fields_changed": ["email"],
        "issues_before": ["personal_email_only"],
        "issues_after": [],
    }
    assert "secret.person" not in str(audit.summary)


@pytest.mark.parametrize("bad_name", ["Email", "has space", "1st", "x" * 65, ""])
def test_fix_rejects_bad_field_names(db_session: Session, bad_name: str) -> None:
    """Field names must be lowercase snake case, so a typo or hostile key is never stored."""
    rep = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=rep)

    with pytest.raises(QuarantineFieldError):
        quarantine.fix_item(db_session, rep, record.id, {bad_name: "x"})

    assert _audit_actions(db_session) == []


def test_fix_rejects_a_value_that_is_too_long(db_session: Session) -> None:
    """A text value above the length limit is refused."""
    rep = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=rep)

    with pytest.raises(QuarantineFieldError):
        quarantine.fix_item(
            db_session, rep, record.id, {"notes": "x" * (quarantine.MAX_VALUE_LENGTH + 1)}
        )


def test_fix_of_a_resolved_record_is_refused(db_session: Session) -> None:
    """A released or discarded record can no longer be edited."""
    rep = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=rep)
    quarantine.discard_item(db_session, rep, record.id)

    with pytest.raises(QuarantineNotOpenError):
        quarantine.fix_item(db_session, rep, record.id, {"email": "jane@acme.com"})


def test_fix_of_an_unknown_record_raises(db_session: Session) -> None:
    """Fixing an id that does not exist raises QuarantineNotFoundError."""
    rep = _user(db_session, UserRole.REP)

    with pytest.raises(QuarantineNotFoundError):
        quarantine.fix_item(db_session, rep, uuid.uuid4(), {"email": "a@b.com"})


# --- release -----------------------------------------------------------------------------------


def test_release_with_remaining_issues_keeps_the_record_open(db_session: Session) -> None:
    """Release revalidates first: a still-invalid row stays open and ingest_row is not called."""
    rep = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=rep)
    ingest = RecordingIngest(RowOutcome(kind=RowOutcomeKind.IMPORTED))

    result = quarantine.release_item(db_session, rep, record.id, ingest)

    assert result.released is False
    assert result.outcome is None
    assert result.item.record.status == QuarantineStatus.OPEN
    assert result.item.record.issues == ["personal_email_only"]
    assert ingest.calls == []
    assert _audit_actions(db_session) == []


def test_release_of_a_fixed_row_goes_through_ingest_row(db_session: Session) -> None:
    """A valid row is sent to ingest_row as a quarantine release, then marked released."""
    rep = _user(db_session, UserRole.REP)
    importer = _user(db_session, UserRole.REP)
    person = make_person(db_session)
    record, raw_row, import_file = _parked(
        db_session, importer=importer, payload=dict(VALID_PAYLOAD)
    )
    ingest = RecordingIngest(RowOutcome(kind=RowOutcomeKind.IMPORTED, person_id=person.id))

    result = quarantine.release_item(db_session, rep, record.id, ingest)

    assert result.released is True
    assert result.outcome == RowOutcomeKind.IMPORTED
    assert record.status == QuarantineStatus.RELEASED
    assert record.resolved_by == rep.id
    assert record.resolved_at is not None
    assert raw_row.person_id == person.id
    ((row, context),) = ingest.calls
    assert row.import_file_id == import_file.id
    assert row.row_number == raw_row.row_number
    assert row.values == VALID_PAYLOAD
    assert context.source == IngestSource.QUARANTINE_RELEASE
    assert context.uploaded_by == importer.id
    assert _audit_actions(db_session) == ["quarantine.released"]


def test_release_after_a_fix_in_two_steps(db_session: Session) -> None:
    """Fix then release: the typical path of a personal-email row once BD adds a work email."""
    rep = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=rep)
    quarantine.fix_item(db_session, rep, record.id, {"email": "jane@acme.com"})
    ingest = RecordingIngest(RowOutcome(kind=RowOutcomeKind.IMPORTED))

    result = quarantine.release_item(db_session, rep, record.id, ingest)

    assert result.released is True
    assert _audit_actions(db_session) == ["quarantine.fixed", "quarantine.released"]


def test_release_counts_a_possible_duplicate_as_released(db_session: Session) -> None:
    """A row imported as a possible duplicate (D-092) is still a lead, so the record resolves."""
    rep = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=rep, payload=dict(VALID_PAYLOAD))
    ingest = RecordingIngest(RowOutcome(kind=RowOutcomeKind.POSSIBLE_DUPLICATE))

    result = quarantine.release_item(db_session, rep, record.id, ingest)

    assert result.released is True
    assert record.status == QuarantineStatus.RELEASED


@pytest.mark.parametrize("kind", [RowOutcomeKind.QUARANTINED, RowOutcomeKind.REJECTED])
def test_release_stays_open_when_ingest_row_still_refuses(
    db_session: Session, kind: RowOutcomeKind
) -> None:
    """If ingest_row quarantines or rejects the row again, the record stays open with its reason."""
    rep = _user(db_session, UserRole.REP)
    record, raw_row, _ = _parked(db_session, importer=rep, payload=dict(VALID_PAYLOAD))
    ingest = RecordingIngest(RowOutcome(kind=kind, reason_code="some_rule"))

    result = quarantine.release_item(db_session, rep, record.id, ingest)

    assert result.released is False
    assert result.outcome == kind
    assert record.status == QuarantineStatus.OPEN
    assert record.issues == ["some_rule"]
    assert raw_row.person_id is None


def test_release_without_ingest_row_raises_and_changes_nothing(db_session: Session) -> None:
    """Until ingest_row exists, a valid row cannot be released and stays open."""
    rep = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=rep, payload=dict(VALID_PAYLOAD))

    def unavailable(session: Session, row: SourceRow, ctx: ImportContext) -> RowOutcome:
        raise IngestUnavailableError

    with pytest.raises(IngestUnavailableError):
        quarantine.release_item(db_session, rep, record.id, unavailable)

    assert record.status == QuarantineStatus.OPEN
    assert _audit_actions(db_session) == []


def test_release_of_a_record_without_a_raw_row_raises(db_session: Session) -> None:
    """A record with no linked raw row has no source file, so it cannot be re-ingested."""
    rep = _user(db_session, UserRole.REP)
    record = make_quarantine_record(db_session, payload=dict(VALID_PAYLOAD), issues=[])

    with pytest.raises(QuarantineNotReleasableError):
        quarantine.release_item(
            db_session, rep, record.id, RecordingIngest(RowOutcome(kind=RowOutcomeKind.IMPORTED))
        )


def test_release_twice_is_refused(db_session: Session) -> None:
    """A released record cannot be released again, so a lead is never created twice."""
    rep = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=rep, payload=dict(VALID_PAYLOAD))
    ingest = RecordingIngest(RowOutcome(kind=RowOutcomeKind.IMPORTED))
    quarantine.release_item(db_session, rep, record.id, ingest)

    with pytest.raises(QuarantineNotOpenError):
        quarantine.release_item(db_session, rep, record.id, ingest)

    assert len(ingest.calls) == 1


# --- discard -----------------------------------------------------------------------------------


@pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.ADMIN])
def test_manager_and_admin_may_discard_any_record(db_session: Session, role: UserRole) -> None:
    """A manager or an admin may discard a record someone else imported (D-107)."""
    importer = _user(db_session, UserRole.REP)
    actor = _user(db_session, role)
    record, _, _ = _parked(db_session, importer=importer)

    quarantine.discard_item(db_session, actor, record.id)

    assert record.status == QuarantineStatus.DISCARDED
    assert record.resolved_by == actor.id
    assert _audit_actions(db_session) == ["quarantine.discarded"]


def test_the_importer_may_discard_their_own_record(db_session: Session) -> None:
    """The rep who uploaded the file may discard its rows."""
    importer = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=importer)

    quarantine.discard_item(db_session, importer, record.id)

    assert record.status == QuarantineStatus.DISCARDED


def test_another_rep_may_not_discard(db_session: Session) -> None:
    """A rep who did not upload the file cannot discard its rows, and nothing changes."""
    importer = _user(db_session, UserRole.REP)
    other_rep = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=importer)

    with pytest.raises(PermissionDeniedError):
        quarantine.discard_item(db_session, other_rep, record.id)

    assert record.status == QuarantineStatus.OPEN
    assert _audit_actions(db_session) == []


def test_rep_may_not_discard_when_the_importer_is_unknown(db_session: Session) -> None:
    """If the uploader's account was deleted, only a manager or an admin may discard."""
    rep = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=None)

    with pytest.raises(PermissionDeniedError):
        quarantine.discard_item(db_session, rep, record.id)


def test_inactive_user_may_not_fix_release_or_discard(db_session: Session) -> None:
    """A disabled account is refused even if its role would allow the action."""
    importer = make_user(db_session, role=UserRole.REP, is_active=False)
    record, _, _ = _parked(db_session, importer=importer)

    with pytest.raises(PermissionDeniedError):
        quarantine.fix_item(db_session, importer, record.id, {"email": "a@b.com"})
    with pytest.raises(PermissionDeniedError):
        quarantine.discard_item(db_session, importer, record.id)


def test_discard_twice_is_refused(db_session: Session) -> None:
    """A discarded record cannot be discarded or released again."""
    rep = _user(db_session, UserRole.REP)
    record, _, _ = _parked(db_session, importer=rep, payload=dict(VALID_PAYLOAD))
    quarantine.discard_item(db_session, rep, record.id)

    with pytest.raises(QuarantineNotOpenError):
        quarantine.discard_item(db_session, rep, record.id)
    with pytest.raises(QuarantineNotOpenError):
        quarantine.release_item(
            db_session, rep, record.id, RecordingIngest(RowOutcome(kind=RowOutcomeKind.IMPORTED))
        )


def test_discard_keeps_the_raw_row(db_session: Session) -> None:
    """Discarding never deletes the raw row: only erase-person removes it (D-099)."""
    rep = _user(db_session, UserRole.REP)
    record, raw_row, _ = _parked(db_session, importer=rep)

    quarantine.discard_item(db_session, rep, record.id)

    assert db_session.get(RawRow, raw_row.id) is not None
