"""Tests for the email structure, structure section and config version tables.

Needed because the schema keeps one structure per email step, unique and ordered sections
(D-084, D-112) and unique version numbering for restore (D-112) until the M4 admin services
exist. Runs against real PostgreSQL through the shared db_session fixture; all data is
synthetic (M1 task B6).
"""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.content.models import (
    ConfigType,
    ConfigVersion,
    EmailStructure,
    EmailStructureStep,
    SectionKind,
    StructureSection,
)
from app.core.models import User

Rejected = Callable[[object, str], None]


def _structure(db_session: Session, step: EmailStructureStep) -> EmailStructure:
    """Insert and return a synthetic email structure for the given step."""
    structure = EmailStructure(step=step, name=f"Structure {step.value}", max_words=120)
    db_session.add(structure)
    db_session.flush()
    return structure


# --- email_structures ---


def test_duplicate_structure_step_is_rejected(
    db_session: Session, assert_rejected: Rejected
) -> None:
    """Two structures for the same email step violate the unique step."""
    _structure(db_session, EmailStructureStep.FIRST_EMAIL)

    assert_rejected(
        EmailStructure(step=EmailStructureStep.FIRST_EMAIL, name="Again", max_words=100),
        "uq_email_structures_step",
    )


def test_structure_word_limits_accept_a_valid_range(db_session: Session) -> None:
    """A first-email structure with 80-120 words is valid."""
    structure = EmailStructure(
        step=EmailStructureStep.FIRST_EMAIL, name="First", min_words=80, max_words=120
    )
    db_session.add(structure)
    db_session.flush()

    assert (structure.min_words, structure.max_words) == (80, 120)


def test_structure_min_words_above_max_is_rejected(assert_rejected: Rejected) -> None:
    """A minimum word count above the maximum is rejected."""
    assert_rejected(
        EmailStructure(step=EmailStructureStep.FOLLOW_UP_1, name="F1", min_words=100, max_words=70),
        "ck_email_structures_min_words_in_range",
    )


def test_structure_zero_max_words_is_rejected(assert_rejected: Rejected) -> None:
    """A maximum word count of zero is rejected."""
    assert_rejected(
        EmailStructure(step=EmailStructureStep.FOLLOW_UP_2, name="F2", max_words=0),
        "ck_email_structures_max_words_positive",
    )


# --- structure_sections ---


def test_section_defaults(db_session: Session) -> None:
    """A new section is not optional and has empty content and no character limit."""
    structure = _structure(db_session, EmailStructureStep.FIRST_EMAIL)
    section = StructureSection(
        structure_id=structure.id, position=1, kind=SectionKind.FIXED, name="Greeting"
    )
    db_session.add(section)
    db_session.flush()
    db_session.refresh(section)

    assert section.is_optional is False
    assert section.content == ""
    assert section.max_chars is None


def test_duplicate_section_position_is_rejected(db_session: Session) -> None:
    """Two sections at the same position of one structure fail the unique check."""
    structure = _structure(db_session, EmailStructureStep.FIRST_EMAIL)
    for name in ("Opening", "Relevance"):
        db_session.add(
            StructureSection(structure_id=structure.id, position=1, kind=SectionKind.AI, name=name)
        )
    db_session.flush()

    # The constraint is DEFERRABLE INITIALLY DEFERRED (so sections can be reordered), which
    # means it is normally checked at commit time; forcing it to IMMEDIATE checks it now.
    with (
        pytest.raises(IntegrityError, match="uq_structure_sections_structure_id_position"),
        db_session.begin_nested(),
    ):
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_section_positions_can_be_swapped_in_one_transaction(db_session: Session) -> None:
    """Swapping two sections' positions works because the unique check is deferred."""
    structure = _structure(db_session, EmailStructureStep.FIRST_EMAIL)
    first = StructureSection(
        structure_id=structure.id, position=1, kind=SectionKind.FIXED, name="Greeting"
    )
    second = StructureSection(
        structure_id=structure.id, position=2, kind=SectionKind.AI, name="Opening"
    )
    db_session.add_all([first, second])
    db_session.flush()

    first.position, second.position = 2, 1
    db_session.flush()
    db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))  # the swap passes the check

    assert (first.position, second.position) == (2, 1)


def test_section_position_zero_is_rejected(db_session: Session, assert_rejected: Rejected) -> None:
    """Positions start at 1; zero is rejected."""
    structure = _structure(db_session, EmailStructureStep.FIRST_EMAIL)

    assert_rejected(
        StructureSection(structure_id=structure.id, position=0, kind=SectionKind.AI, name="Bad"),
        "ck_structure_sections_position_positive",
    )


def test_section_zero_max_chars_is_rejected(db_session: Session, assert_rejected: Rejected) -> None:
    """A character limit of zero is rejected."""
    structure = _structure(db_session, EmailStructureStep.FIRST_EMAIL)

    assert_rejected(
        StructureSection(
            structure_id=structure.id,
            position=1,
            kind=SectionKind.AI,
            name="Subject",
            max_chars=0,
        ),
        "ck_structure_sections_max_chars_positive",
    )


def test_deleting_structure_deletes_its_sections(db_session: Session) -> None:
    """Deleting a structure cascades to its sections."""
    structure = _structure(db_session, EmailStructureStep.FIRST_EMAIL)
    db_session.add(
        StructureSection(
            structure_id=structure.id, position=1, kind=SectionKind.FIXED, name="Greeting"
        )
    )
    db_session.flush()

    db_session.execute(delete(EmailStructure).where(EmailStructure.id == structure.id))

    assert db_session.scalar(select(func.count()).select_from(StructureSection)) == 0


# --- config_versions ---


def _version(config_id: uuid.UUID, number: int = 1, **overrides: object) -> ConfigVersion:
    """Build a synthetic version snapshot for a configuration id."""
    fields: dict[str, object] = {
        "config_type": ConfigType.VOICE,
        "config_id": config_id,
        "version_number": number,
        "snapshot": {"tone": "clear, practical, peer-to-peer"},
    }
    fields.update(overrides)
    return ConfigVersion(**fields)


def test_config_version_keeps_snapshot_json(db_session: Session) -> None:
    """A snapshot round-trips as JSON and created_at is filled from the clock."""
    version = _version(uuid.uuid4())
    db_session.add(version)
    db_session.flush()
    db_session.refresh(version)

    assert version.snapshot == {"tone": "clear, practical, peer-to-peer"}
    assert version.created_at is not None


def test_duplicate_version_number_is_rejected(
    db_session: Session, assert_rejected: Rejected
) -> None:
    """The same configuration cannot have two snapshots with one version number."""
    config_id = uuid.uuid4()
    db_session.add(_version(config_id, 1))
    db_session.flush()

    assert_rejected(_version(config_id, 1), "uq_config_versions_config_type_config_id_version")


def test_same_version_number_for_different_configs_is_accepted(db_session: Session) -> None:
    """Different configurations each start at version 1."""
    db_session.add_all([_version(uuid.uuid4(), 1), _version(uuid.uuid4(), 1)])
    db_session.flush()

    assert db_session.scalar(select(func.count()).select_from(ConfigVersion)) == 2


def test_version_number_zero_is_rejected(assert_rejected: Rejected) -> None:
    """Version numbers start at 1; zero is rejected."""
    assert_rejected(_version(uuid.uuid4(), 0), "ck_config_versions_version_number_positive")


def test_deleting_author_keeps_version(db_session: Session, user: User) -> None:
    """Deleting the user who saved a snapshot keeps it and clears created_by."""
    version = _version(uuid.uuid4(), created_by=user.id)
    db_session.add(version)
    db_session.flush()

    db_session.execute(delete(User).where(User.id == user.id))
    db_session.refresh(version)

    assert version.created_by is None
