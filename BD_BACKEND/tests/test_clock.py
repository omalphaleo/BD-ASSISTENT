"""Tests for app.core.clock: UTC awareness and the test-only offset.

Needed because every time-dependent rule reads time through clock.now(); these tests lock
in that now() is timezone-aware UTC and that set_offset()/reset_offset() shift it correctly.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import now, reset_offset, set_offset


@pytest.fixture(autouse=True)
def clean_offset() -> Iterator[None]:
    """Reset the module-level clock offset before and after each test.

    The offset is process-wide state, so without this a failing test could leave the clock
    shifted and break every later test.
    """
    reset_offset()
    yield
    reset_offset()


def test_now_is_timezone_aware_utc() -> None:
    """now() returns an aware datetime whose UTC offset is zero."""
    current = now()
    assert current.tzinfo is not None
    assert current.utcoffset() == timedelta(0)


def test_now_matches_real_utc_without_offset() -> None:
    """With no offset set, now() is within 2 seconds of the real UTC time."""
    assert abs(now() - datetime.now(UTC)) < timedelta(seconds=2)


def test_positive_offset_moves_now_ahead() -> None:
    """A +2h offset makes now() about two hours ahead of real UTC (5s tolerance)."""
    set_offset(timedelta(hours=2))
    difference = now() - datetime.now(UTC)
    assert abs(difference - timedelta(hours=2)) < timedelta(seconds=5)


def test_negative_offset_moves_now_behind() -> None:
    """A -3h offset makes now() about three hours behind real UTC (5s tolerance)."""
    set_offset(timedelta(hours=-3))
    difference = now() - datetime.now(UTC)
    assert abs(difference - timedelta(hours=-3)) < timedelta(seconds=5)


def test_reset_offset_returns_to_real_utc() -> None:
    """After set_offset(+5h) then reset_offset(), now() is back within 2s of real UTC."""
    set_offset(timedelta(hours=5))
    reset_offset()
    assert abs(now() - datetime.now(UTC)) < timedelta(seconds=2)
