"""Shared helpers for the test factories: a unique-number counter and a persist function.

Needed so every factory builds rows the same way and gives each call unique default values
(emails, names, hashes) that never collide on a UNIQUE constraint; core, leads, imports and
compliance factories import these two helpers instead of repeating them.
"""

import itertools

from sqlalchemy.orm import Session

# One counter for the whole test run: any two factory calls get different numbers, so
# defaults such as "rep7@example.com" or a row number stay unique without bookkeeping.
_counter = itertools.count(1)


def next_number() -> int:
    """Return the next unique positive integer (1, 2, 3, ...) for building default values."""
    return next(_counter)


def persist[Row](session: Session, row: Row) -> Row:
    """Add the row to the session and flush it so its database defaults and id are filled.

    It never commits: the db_session fixture rolls everything back after each test.
    """
    session.add(row)
    session.flush()
    return row
