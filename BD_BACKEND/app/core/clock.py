"""Single source of application time (UTC), with an optional offset for testing."""

from datetime import UTC, datetime, timedelta

_offset: timedelta = timedelta(0)


def now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime, shifted by the offset."""
    # The only place in the codebase allowed to read the system clock.
    return datetime.now(UTC) + _offset


def set_offset(delta: timedelta) -> None:
    """Shift every later now() call by delta (use a negative delta to go back in time)."""
    global _offset
    _offset = delta


def reset_offset() -> None:
    """Remove the offset so now() returns real UTC again."""
    global _offset
    _offset = timedelta(0)
