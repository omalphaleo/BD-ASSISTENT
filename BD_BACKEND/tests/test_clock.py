from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import now, reset_offset, set_offset


@pytest.fixture(autouse=True)
def clean_offset() -> Iterator[None]:
    reset_offset()
    yield
    reset_offset()


def test_now_is_timezone_aware_utc() -> None:
    current = now()
    assert current.tzinfo is not None
    assert current.utcoffset() == timedelta(0)


def test_now_matches_real_utc_without_offset() -> None:
    assert abs(now() - datetime.now(UTC)) < timedelta(seconds=2)


def test_positive_offset_moves_now_ahead() -> None:
    set_offset(timedelta(hours=2))
    difference = now() - datetime.now(UTC)
    assert abs(difference - timedelta(hours=2)) < timedelta(seconds=5)


def test_negative_offset_moves_now_behind() -> None:
    set_offset(timedelta(hours=-3))
    difference = now() - datetime.now(UTC)
    assert abs(difference - timedelta(hours=-3)) < timedelta(seconds=5)


def test_reset_offset_returns_to_real_utc() -> None:
    set_offset(timedelta(hours=5))
    reset_offset()
    assert abs(now() - datetime.now(UTC)) < timedelta(seconds=2)
