"""Tests for matching a source owner name to an app user (D-075) on a real PostgreSQL database.

Needed because a wrong match would hand a lead to the wrong person: only an unambiguous match
on an active user's email (full address, or the words of its local part) may resolve; anything
else must stay Unassigned. Synthetic users only.
"""

from factories.core import make_user
from sqlalchemy.orm import Session

from app.imports.owners import build_owner_index, resolve_owner


def test_full_email_resolves_case_insensitively(db_session: Session) -> None:
    """An owner text that is a user's email matches regardless of case and spaces."""
    user = make_user(db_session, email="jane.doe@example.com")
    index = build_owner_index(db_session)

    assert resolve_owner(index, "  Jane.Doe@Example.com ") == user.id


def test_name_matches_the_words_of_the_email_local_part(db_session: Session) -> None:
    """'Jane Doe' matches jane.doe@, jane_doe@ and jane-doe@ users."""
    dotted = make_user(db_session, email="jane.doe@example.com")
    underscored = make_user(db_session, email="sam_lee@example.com")
    index = build_owner_index(db_session)

    assert resolve_owner(index, "Jane Doe") == dotted.id
    assert resolve_owner(index, "sam lee") == underscored.id


def test_ambiguous_name_stays_unassigned(db_session: Session) -> None:
    """Two users whose local parts read the same make the name ambiguous: None, not a guess."""
    make_user(db_session, email="jane.doe@example.com")
    make_user(db_session, email="jane_doe@example.org")
    index = build_owner_index(db_session)

    assert resolve_owner(index, "Jane Doe") is None


def test_unknown_blank_and_none_names_stay_unassigned(db_session: Session) -> None:
    """An unknown name, a blank text and None all resolve to None."""
    make_user(db_session, email="jane.doe@example.com")
    index = build_owner_index(db_session)

    assert resolve_owner(index, "Somebody Else") is None
    assert resolve_owner(index, "   ") is None
    assert resolve_owner(index, None) is None


def test_inactive_users_are_ignored(db_session: Session) -> None:
    """A deactivated user can no longer receive leads, so their name does not resolve."""
    make_user(db_session, email="jane.doe@example.com", is_active=False)
    index = build_owner_index(db_session)

    assert resolve_owner(index, "Jane Doe") is None
