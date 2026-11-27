"""Matching the owner name of a source file to an app user (D-075).

Needed because spreadsheets name the lead's owner as text ("Jane Doe") while the app assigns
leads to users. users have no name column, so a name is matched against the user's email:
either the full email, or the local part split into words ("jane.doe@..." is "Jane Doe").
The pipeline calls build_owner_index() once per run and resolve_owner() per row; an ambiguous
or unknown name returns None, which leaves the lead in the Unassigned pool for a manager.
"""

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.models import User
from app.leads.models import Person

# Words inside an email local part or a person's name are separated by these characters.
_WORD_SEPARATORS = re.compile(r"[\s._\-+]+")


def _words(text: str) -> tuple[str, ...]:
    """Lowercase words of a name or email local part, with empty pieces dropped."""
    return tuple(word for word in _WORD_SEPARATORS.split(text.strip().lower()) if word)


@dataclass(frozen=True, slots=True)
class OwnerIndex:
    """Active users looked up by full email or by the words of the email local part.

    Both maps hold sets, so two users that share a name show up as ambiguous instead of one
    silently winning.
    """

    by_email: dict[str, set[uuid.UUID]] = field(default_factory=dict)
    by_words: dict[tuple[str, ...], set[uuid.UUID]] = field(default_factory=dict)


def build_owner_index(db: Session) -> OwnerIndex:
    """Load every active user once and index them for resolve_owner()."""
    by_email: dict[str, set[uuid.UUID]] = defaultdict(set)
    by_words: dict[tuple[str, ...], set[uuid.UUID]] = defaultdict(set)
    for user_id, email in db.execute(select(User.id, User.email).where(User.is_active.is_(True))):
        by_email[email.lower()].add(user_id)
        by_words[_words(email.split("@", 1)[0])].add(user_id)
    return OwnerIndex(by_email=dict(by_email), by_words=dict(by_words))


def resolve_owner(index: OwnerIndex, owner_name: str | None) -> uuid.UUID | None:
    """Return the user a source owner name refers to, or None (Unassigned).

    A text with "@" is matched as a full email; anything else is matched as words against the
    email local parts. None is returned for blank, unknown and ambiguous names.
    """
    if owner_name is None or not owner_name.strip():
        return None
    text = owner_name.strip().lower()
    matches = index.by_email.get(text, set()) if "@" in text else index.by_words.get(_words(text))
    if matches is not None and len(matches) == 1:
        return next(iter(matches))
    return None


def assign_owner_if_empty(db: Session, person_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Set the person's owner only when none is set, so an import never takes a lead away.

    Ownership is for assignment and notifications, not a lock (D-001, D-075); the conditional
    UPDATE keeps an owner chosen by a manager or by an earlier import.
    """
    db.execute(
        update(Person)
        .where(Person.id == person_id, Person.owner_id.is_(None))
        .values(owner_id=user_id)
    )
