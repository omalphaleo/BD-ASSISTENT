"""Tests for the knowledge base tables: knowledge items and their embeddings.

Needed because the schema enforces the draft / approved / retired rules that decide what the
AI may see (D-088), keeps at most one vector per item and fixes the vector size at 768, until
the M4 knowledge service and embedding job exist. Runs against real PostgreSQL through the
shared db_session fixture; all data is synthetic (M1 task B6).
"""

from collections.abc import Callable

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.content.models import (
    EMBEDDING_DIMENSION,
    KnowledgeEmbedding,
    KnowledgeItem,
    KnowledgeItemStatus,
    KnowledgeItemType,
)
from app.core.clock import now
from app.core.models import User

Rejected = Callable[[object, str], None]

HASH = "a" * 64


def _item(**overrides: object) -> KnowledgeItem:
    """Build a synthetic draft knowledge item, with optional field overrides."""
    fields: dict[str, object] = {
        "type": KnowledgeItemType.SOLUTION,
        "title": "Salesforce implementation",
        "body": "We implement Salesforce for mid-market teams.",
        "content_hash": HASH,
    }
    fields.update(overrides)
    return KnowledgeItem(**fields)


def _embedding(item: KnowledgeItem, **overrides: object) -> KnowledgeEmbedding:
    """Build a synthetic embedding row for an item, with optional field overrides."""
    fields: dict[str, object] = {
        "knowledge_item_id": item.id,
        "embedding": [0.1] * EMBEDDING_DIMENSION,
        "model_name": "fake-embedding-model",
        "dimension": EMBEDDING_DIMENSION,
        "content_hash": HASH,
    }
    fields.update(overrides)
    return KnowledgeEmbedding(**fields)


# --- knowledge_items ---


def test_knowledge_item_defaults(db_session: Session) -> None:
    """A new item is a draft with empty tags, no approver and no timestamps for approval."""
    item = _item()
    db_session.add(item)
    db_session.flush()
    db_session.refresh(item)

    assert item.status is KnowledgeItemStatus.DRAFT
    assert item.size_tags == []
    assert item.industry_tags == []
    assert item.approved_at is None
    assert item.retired_at is None


def test_knowledge_item_keeps_tags(db_session: Session) -> None:
    """Size and industry tags round-trip as lists."""
    item = _item(size_tags=["smb", "mid_market"], industry_tags=["healthcare"])
    db_session.add(item)
    db_session.flush()
    db_session.refresh(item)

    assert item.size_tags == ["smb", "mid_market"]
    assert item.industry_tags == ["healthcare"]


def test_approved_item_with_timestamp_is_accepted(db_session: Session) -> None:
    """An approved item that has approved_at is valid."""
    item = _item(status=KnowledgeItemStatus.APPROVED, approved_at=now())
    db_session.add(item)
    db_session.flush()

    assert item.status is KnowledgeItemStatus.APPROVED


def test_approved_item_without_approved_at_is_rejected(assert_rejected: Rejected) -> None:
    """Status approved without approved_at violates the status/timestamp CHECK."""
    assert_rejected(
        _item(status=KnowledgeItemStatus.APPROVED),
        "ck_knowledge_items_status_matches_timestamps",
    )


def test_retired_item_without_retired_at_is_rejected(assert_rejected: Rejected) -> None:
    """Status retired without retired_at violates the status/timestamp CHECK."""
    assert_rejected(
        _item(status=KnowledgeItemStatus.RETIRED, approved_at=now()),
        "ck_knowledge_items_status_matches_timestamps",
    )


def test_retired_item_keeps_its_approval_history(db_session: Session) -> None:
    """A retired item may keep approved_at from when it was approved."""
    item = _item(status=KnowledgeItemStatus.RETIRED, approved_at=now(), retired_at=now())
    db_session.add(item)
    db_session.flush()

    assert item.approved_at is not None


def test_draft_item_with_retired_at_is_rejected(assert_rejected: Rejected) -> None:
    """A draft cannot already carry a retired_at."""
    assert_rejected(
        _item(retired_at=now()), "ck_knowledge_items_status_matches_timestamps"
    )


def test_unknown_status_is_rejected(db_session: Session) -> None:
    """A status outside draft / approved / retired is rejected by the CHECK."""
    item = _item()
    db_session.add(item)
    db_session.flush()

    # Raw SQL: the enum column would refuse 'deleted' before the database ever saw it. Both
    # the status-list CHECK and the status/timestamp CHECK reject it; PostgreSQL reports
    # whichever it evaluates first, so the test only requires a CHECK violation.
    with (
        pytest.raises(IntegrityError, match="violates check constraint"),
        db_session.begin_nested(),
    ):
        db_session.execute(
            text("UPDATE knowledge_items SET status = 'deleted' WHERE id = :id"),
            {"id": item.id},
        )


def test_deleting_author_keeps_item(db_session: Session, user: User) -> None:
    """Deleting the user who wrote the item keeps the item and clears created_by."""
    item = _item(created_by=user.id)
    db_session.add(item)
    db_session.flush()

    db_session.execute(delete(User).where(User.id == user.id))
    db_session.refresh(item)

    assert item.created_by is None


# --- knowledge_embeddings ---


def test_embedding_round_trips(db_session: Session) -> None:
    """A 768-number vector is stored with its model name and read back with the same size."""
    item = _item()
    db_session.add(item)
    db_session.flush()
    db_session.add(_embedding(item))
    db_session.flush()

    stored = db_session.scalars(select(KnowledgeEmbedding)).one()

    assert len(stored.embedding) == EMBEDDING_DIMENSION
    assert stored.model_name == "fake-embedding-model"


def test_second_embedding_for_same_item_is_rejected(
    db_session: Session, assert_rejected: Rejected
) -> None:
    """An item has at most one embedding."""
    item = _item()
    db_session.add(item)
    db_session.flush()
    db_session.add(_embedding(item))
    db_session.flush()

    assert_rejected(_embedding(item), "uq_knowledge_embeddings_knowledge_item_id")


def test_embedding_with_wrong_vector_size_is_rejected(db_session: Session) -> None:
    """A vector that is not 768 numbers long is rejected by the vector(768) column type."""
    item = _item()
    db_session.add(item)
    db_session.flush()

    # pgvector reports a size mismatch as a data error, not an integrity error.
    with (
        pytest.raises(DataError, match="expected 768 dimensions"),
        db_session.begin_nested(),
    ):
        db_session.add(_embedding(item, embedding=[0.1] * 3))
        db_session.flush()


def test_embedding_with_wrong_recorded_dimension_is_rejected(
    db_session: Session, assert_rejected: Rejected
) -> None:
    """A recorded dimension other than 768 is rejected by the CHECK."""
    item = _item()
    db_session.add(item)
    db_session.flush()

    assert_rejected(_embedding(item, dimension=1536), "ck_knowledge_embeddings_dimension_matches")


def test_deleting_item_deletes_its_embedding(db_session: Session) -> None:
    """Deleting a knowledge item cascades to its embedding."""
    item = _item()
    db_session.add(item)
    db_session.flush()
    db_session.add(_embedding(item))
    db_session.flush()

    db_session.execute(delete(KnowledgeItem).where(KnowledgeItem.id == item.id))

    assert db_session.scalar(select(func.count()).select_from(KnowledgeEmbedding)) == 0
