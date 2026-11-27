"""Data types of the eligibility service: reasons, warnings, result and context (M3-A1).

Needed so search, campaigns, drafting and sending all speak one vocabulary when they ask
"may we contact this person, and if not, why not?" (plan section 14 G). eligibility.py
produces these values; callers only read them and never reach into the rules themselves.
"""

import enum
from dataclasses import dataclass
from datetime import datetime

# Contact limit: a person with this many outbound emails inside the window is not eligible
# (D-020, D-083; decision 1 of the M3-A1 plan). Constants until M5 makes them admin settings.
CONTACT_LIMIT = 3
CONTACT_WINDOW_DAYS = 30


class EligibilityReason(enum.StrEnum):
    """Why a person may not be contacted. The declaration order is the order reasons are listed."""

    OPTED_OUT = "opted_out"  # an address of the person has an active opt-out (D-066)
    NO_USABLE_EMAIL = "no_usable_email"  # no work address that is not invalid (D-072, D-073)
    REPLIED = "replied"  # the person replied (D-073, D-082)
    QUALIFIED_OR_HANDED_OFF = "qualified_or_handed_off"  # set by a BD user (D-101)
    POSSIBLE_DUPLICATE = "possible_duplicate"  # an open duplicate pair involves them (D-092)
    COOLING_OFF = "cooling_off"  # contacted inside the cooling-off period (D-073, D-083)
    CONTACT_LIMIT = "contact_limit"  # too many emails in the recent window (D-020, D-083)


class EligibilityWarning(enum.StrEnum):
    """A caution shown to BD that does not block contact."""

    UNVERIFIED_EMAIL = "unverified_email"  # deliverability warning, not a block (D-042)


@dataclass(frozen=True, slots=True)
class EligibilityContext:
    """The inputs every rule shares, so the SQL and record versions use the same values.

    Attributes:
        now: The moment eligibility is judged (from core.clock.now()).
        cooling_off_days: Length of the cooling-off period after a contact.
        contact_limit: Outbound emails inside the window at which a person is not eligible.
        contact_window_days: Length of the contact-limit window.
    """

    now: datetime
    cooling_off_days: int
    contact_limit: int = CONTACT_LIMIT
    contact_window_days: int = CONTACT_WINDOW_DAYS


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    """The answer for one person.

    Attributes:
        reasons: Every reason that blocks contact, in EligibilityReason order; empty = eligible.
        warnings: Cautions that do not block.
    """

    reasons: tuple[EligibilityReason, ...]
    warnings: tuple[EligibilityWarning, ...] = ()

    @property
    def eligible(self) -> bool:
        """True when no reason blocks contact."""
        return not self.reasons
