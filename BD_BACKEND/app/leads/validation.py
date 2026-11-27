"""Row validation for imports: the two mandatory fields and the email rules (module C).

Needed so every import row gets a clear verdict before it reaches matching or merge: a row
with no issues continues, a row with issues is quarantined (M2-B2 stores it) so a bad row
never fails the file (D-068). Only two things are mandatory, a usable work email and a first
name (D-069); every other field is optional and is never checked here. M2-B4's ingest_row
calls validate_row() and acts on the result.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.leads.normalization import (
    EmailKind,
    classify_email,
    has_letters,
    normalize_email_address,
    normalize_name,
)

# Apollo's email-status wording for an address it could not confirm (D-042, Q-IMPORT-04).
APOLLO_UNVERIFIED_STATUS = "unverified"


class RowIssue(StrEnum):
    """Why a row must be quarantined. The values are stored in QuarantineRecord.issues."""

    NO_WORK_EMAIL = "no_work_email"
    PERSONAL_EMAIL_ONLY = "personal_email_only"
    GENERIC_EMAIL_ONLY = "generic_email_only"
    BAD_EMAIL_FORMAT = "bad_email_format"
    MISSING_FIRST_NAME = "missing_first_name"


class RowWarning(StrEnum):
    """A problem that does not block the row but is shown to BD."""

    UNVERIFIED_EMAIL = "unverified_email"


# Which issue each non-work email kind produces when the row has no work email at all.
_ISSUE_BY_EMAIL_KIND: dict[EmailKind, RowIssue] = {
    EmailKind.PERSONAL: RowIssue.PERSONAL_EMAIL_ONLY,
    EmailKind.GENERIC: RowIssue.GENERIC_EMAIL_ONLY,
    EmailKind.INVALID: RowIssue.BAD_EMAIL_FORMAT,
}


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """The verdict for one row.

    Attributes:
        issues: Reasons to quarantine; empty means the row is valid.
        warnings: Notes for BD that do not block the row.
        work_email: The normalized work email to use, or None when there is none.
        first_name: The normalized first name, or None when missing or not a real name.
    """

    issues: tuple[RowIssue, ...]
    warnings: tuple[RowWarning, ...]
    work_email: str | None
    first_name: str | None

    @property
    def is_valid(self) -> bool:
        """True when the row has no issues and may continue to matching and merge."""
        return not self.issues


def validate_row(
    first_name: str | None,
    emails: Sequence[str | None],
    work_email_status: str | None = None,
) -> ValidationResult:
    """Validate one mapped row against the mandatory-field rules (D-068, D-069, D-072).

    Args:
        first_name: The first-name cell as received.
        emails: Every email cell of the row (primary, secondary, tertiary) in priority
            order. The first work email wins; personal, generic and secondary addresses on
            an otherwise valid row are kept by the caller but never make the row invalid.
        work_email_status: The source's verification wording for the email (for Apollo,
            "Verified" or "Unverified"); only used to add a warning.

    Returns:
        A ValidationResult. A row with no work email gets one issue per kind of unusable
        email it has (personal, generic, bad format), or NO_WORK_EMAIL when it has none.
    """
    issues: list[RowIssue] = []
    warnings: list[RowWarning] = []

    cleaned_emails = [email for raw in emails if (email := normalize_email_address(raw))]
    kinds = [classify_email(email) for email in cleaned_emails]

    work_emails = [
        email for email, kind in zip(cleaned_emails, kinds, strict=True) if kind is EmailKind.WORK
    ]
    work_email = work_emails[0] if work_emails else None
    if work_email is None:
        if not cleaned_emails:
            issues.append(RowIssue.NO_WORK_EMAIL)
        else:
            # Report each kind present, in a fixed order, so the reasons are stable.
            for kind, issue in _ISSUE_BY_EMAIL_KIND.items():
                if kind in kinds:
                    issues.append(issue)
    elif (work_email_status or "").strip().lower() == APOLLO_UNVERIFIED_STATUS:
        # Unverified emails stay eligible; BD only sees a deliverability warning (D-042).
        warnings.append(RowWarning.UNVERIFIED_EMAIL)

    cleaned_first_name = normalize_name(first_name)
    # A cell like "-" or "123" is present but is not a name, so it counts as missing.
    if cleaned_first_name is None or not has_letters(cleaned_first_name):
        cleaned_first_name = None
        issues.append(RowIssue.MISSING_FIRST_NAME)

    return ValidationResult(
        issues=tuple(issues),
        warnings=tuple(warnings),
        work_email=work_email,
        first_name=cleaned_first_name,
    )
