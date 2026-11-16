"""Tests for Argon2id password hashing (no database).

Needed because the login flow trusts hash_password()/verify_password()/password_needs_rehash();
these tests pin the hash format, salting, failure handling and rehash detection.
"""

import argon2
import pytest

from app.core.passwords import hash_password, password_needs_rehash, verify_password

PASSWORD = "correct-horse-battery"  # synthetic test value, not a real credential


def test_hash_uses_argon2id() -> None:
    """The hash string starts with the $argon2id$ prefix."""
    assert hash_password(PASSWORD).startswith("$argon2id$")


def test_hash_does_not_contain_plaintext() -> None:
    """The plaintext password does not appear anywhere in the hash string."""
    assert PASSWORD not in hash_password(PASSWORD)


def test_same_password_hashes_differently_and_both_verify() -> None:
    """Hashing twice gives two different hashes (random salt) and both verify."""
    first = hash_password(PASSWORD)
    second = hash_password(PASSWORD)
    assert first != second
    assert verify_password(first, PASSWORD)
    assert verify_password(second, PASSWORD)


def test_correct_password_verifies_and_wrong_one_does_not() -> None:
    """Correct password: True. Wrong password: False, with no exception raised."""
    password_hash = hash_password(PASSWORD)
    assert verify_password(password_hash, PASSWORD) is True
    assert verify_password(password_hash, "wrong-password") is False


def test_unicode_password_round_trips() -> None:
    """A password with accented and CJK characters hashes and verifies correctly."""
    unicode_password = "pässwörd-密码"
    assert verify_password(hash_password(unicode_password), unicode_password)


@pytest.mark.parametrize("bad_hash", ["not-a-hash", ""])
def test_malformed_or_empty_hash_returns_false(bad_hash: str) -> None:
    """A malformed or empty stored hash makes verify_password return False, not raise."""
    assert verify_password(bad_hash, PASSWORD) is False


def test_empty_password_is_rejected() -> None:
    """hash_password("") raises ValueError."""
    with pytest.raises(ValueError):
        hash_password("")


def test_fresh_hash_does_not_need_rehash() -> None:
    """A hash made with the current parameters does not need rehashing."""
    assert password_needs_rehash(hash_password(PASSWORD)) is False


def test_weaker_hash_needs_rehash() -> None:
    """A hash made with weaker parameters than the current ones needs rehashing."""
    # Deliberately weak hasher (minimal time, memory and parallelism) standing in for a
    # hash created before the cost parameters were raised.
    weak_hasher = argon2.PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    assert password_needs_rehash(weak_hasher.hash(PASSWORD)) is True
