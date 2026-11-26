"""Tests for the voice, size-profile and industry-profile tables.

Needed because the schema is what keeps exactly one global voice, one profile per size band
and per industry, and valid employee ranges (D-085) until the M4 admin services exist. Runs
against real PostgreSQL through the shared db_session fixture; all data is synthetic
(M1 task B6).
"""

from collections.abc import Callable

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.content.models import (
    IndustryProfile,
    IndustryProfileItem,
    IndustryProfileKey,
    KnowledgeItem,
    KnowledgeItemType,
    SizeProfile,
    SizeProfileKey,
    VoiceSetting,
)
from app.core.models import User

Rejected = Callable[[object, str], None]


def _knowledge_item(db_session: Session) -> KnowledgeItem:
    """Insert and return a minimal draft knowledge item to link to."""
    item = KnowledgeItem(
        type=KnowledgeItemType.SOLUTION, title="Test solution", body="Body", content_hash="a" * 64
    )
    db_session.add(item)
    db_session.flush()
    return item


# --- voice_settings ---


def test_voice_defaults(db_session: Session) -> None:
    """A new voice has empty texts, no banned words and the singleton flag set."""
    voice = VoiceSetting()
    db_session.add(voice)
    db_session.flush()
    db_session.refresh(voice)

    assert voice.singleton is True
    assert voice.tone == ""
    assert voice.banned_words == []
    assert voice.updated_by is None


def test_second_voice_row_is_rejected(db_session: Session, assert_rejected: Rejected) -> None:
    """Only one voice row can exist (unique index on the singleton column)."""
    db_session.add(VoiceSetting())
    db_session.flush()

    assert_rejected(VoiceSetting(), "uq_voice_settings_singleton")


def test_voice_singleton_false_is_rejected(assert_rejected: Rejected) -> None:
    """The singleton column cannot be false, so the one-row guard cannot be bypassed."""
    assert_rejected(VoiceSetting(singleton=False), "ck_voice_settings_singleton_true")


def test_voice_keeps_banned_words(db_session: Session) -> None:
    """Banned words round-trip as a list."""
    voice = VoiceSetting(banned_words=["synergy", "guarantee"])
    db_session.add(voice)
    db_session.flush()
    db_session.refresh(voice)

    assert voice.banned_words == ["synergy", "guarantee"]


def test_deleting_updating_user_keeps_voice(db_session: Session, user: User) -> None:
    """Deleting the admin who last edited the voice keeps the voice and clears updated_by."""
    voice = VoiceSetting(updated_by=user.id)
    db_session.add(voice)
    db_session.flush()

    db_session.execute(delete(User).where(User.id == user.id))
    db_session.refresh(voice)

    assert voice.updated_by is None


# --- size_profiles ---


def test_size_profile_defaults(db_session: Session) -> None:
    """A new size profile has empty guidance texts and an open-ended maximum when unset."""
    profile = SizeProfile(key=SizeProfileKey.ENTERPRISE, name="Enterprise", min_employees=1001)
    db_session.add(profile)
    db_session.flush()
    db_session.refresh(profile)

    assert profile.key is SizeProfileKey.ENTERPRISE
    assert profile.max_employees is None
    assert profile.pain_points == ""
    assert profile.example_phrases == ""


def test_duplicate_size_profile_key_is_rejected(
    db_session: Session, assert_rejected: Rejected
) -> None:
    """Two profiles for the same size band violate the unique key."""
    db_session.add(SizeProfile(key=SizeProfileKey.SMB, name="SMB", min_employees=1))
    db_session.flush()

    assert_rejected(
        SizeProfile(key=SizeProfileKey.SMB, name="SMB again", min_employees=1),
        "uq_size_profiles_key",
    )


def test_size_profile_max_below_min_is_rejected(assert_rejected: Rejected) -> None:
    """A maximum smaller than the minimum employee count is rejected."""
    assert_rejected(
        SizeProfile(
            key=SizeProfileKey.MID_MARKET, name="Mid", min_employees=201, max_employees=100
        ),
        "ck_size_profiles_employee_range_ordered",
    )


def test_size_profile_negative_min_is_rejected(assert_rejected: Rejected) -> None:
    """A negative minimum employee count is rejected."""
    assert_rejected(
        SizeProfile(key=SizeProfileKey.SMB, name="SMB", min_employees=-1),
        "ck_size_profiles_min_employees_not_negative",
    )


# --- industry_profiles and the knowledge-item link ---


def test_duplicate_industry_profile_key_is_rejected(
    db_session: Session, assert_rejected: Rejected
) -> None:
    """Two profiles for the same industry violate the unique key."""
    db_session.add(IndustryProfile(key=IndustryProfileKey.GENERAL, name="General"))
    db_session.flush()

    assert_rejected(
        IndustryProfile(key=IndustryProfileKey.GENERAL, name="General again"),
        "uq_industry_profiles_key",
    )


def test_industry_profile_links_knowledge_item_once(
    db_session: Session, assert_rejected: Rejected
) -> None:
    """A profile can link an item, but linking the same pair twice is rejected."""
    profile = IndustryProfile(key=IndustryProfileKey.HEALTHCARE, name="Healthcare")
    db_session.add(profile)
    item = _knowledge_item(db_session)
    db_session.flush()
    db_session.add(IndustryProfileItem(industry_profile_id=profile.id, knowledge_item_id=item.id))
    db_session.flush()

    assert_rejected(
        IndustryProfileItem(industry_profile_id=profile.id, knowledge_item_id=item.id),
        "industry_profile_items_pkey",
    )


def test_deleting_knowledge_item_removes_its_profile_links(db_session: Session) -> None:
    """Deleting a knowledge item cascades to its links; the profile stays."""
    profile = IndustryProfile(key=IndustryProfileKey.HOSPITALITY, name="Hospitality")
    db_session.add(profile)
    item = _knowledge_item(db_session)
    db_session.flush()
    link = IndustryProfileItem(industry_profile_id=profile.id, knowledge_item_id=item.id)
    db_session.add(link)
    db_session.flush()

    db_session.execute(delete(KnowledgeItem).where(KnowledgeItem.id == item.id))
    db_session.expire_all()

    assert db_session.get(IndustryProfile, profile.id) is not None
    assert db_session.get(IndustryProfileItem, (profile.id, item.id)) is None
