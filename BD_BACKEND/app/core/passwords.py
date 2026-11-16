"""Password hashing and verification with Argon2id.

Needed so no plaintext password is ever stored; user creation and the (planned) login
flow call these functions and never touch the hashing library directly.
Only hashing lives here: no password-strength rules, sessions or routes.
Passwords and hashes must never be logged or printed.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# We rely on the library defaults (Argon2id, RFC 9106 low-memory profile) and may raise
# the cost parameters later; password_needs_rehash() lets old hashes upgrade on login.
_hasher = PasswordHasher()


def hash_password(plain_password: str) -> str:
    """Return the Argon2id hash string (salt and parameters included) for a password.

    Raises:
        ValueError: if the password is empty.
    """
    if not plain_password:
        raise ValueError("Password must not be empty.")
    return _hasher.hash(plain_password)


def verify_password(password_hash: str, plain_password: str) -> bool:
    """Return True if the password matches the hash.

    Returns False for a wrong password and for a malformed, unrecognised or empty hash.
    """
    try:
        return _hasher.verify(password_hash, plain_password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        # Every failure collapses to False so callers (login) cannot tell a wrong password
        # from a corrupt stored hash, and no library exception text can leak.
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """Return True if the hash was made with weaker parameters than the current ones.

    A malformed hash raises InvalidHashError, so call this only after a successful
    verify_password().
    """
    return _hasher.check_needs_rehash(password_hash)
