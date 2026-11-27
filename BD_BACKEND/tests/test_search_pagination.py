"""Tests for search ordering, paging and the total count on a real PostgreSQL (M3-A2).

Needed because the Leads screen pages through results and "select all matching" shows a count
(m3.md decisions 14 and 16): pages must not repeat or skip rows, the total must cover every
match, and only whitelisted sort fields are accepted. Synthetic leads are tagged with a unique
industry so the tests see only their own rows.
"""

from datetime import UTC, datetime, timedelta

import pytest
from factories.leads import make_company, make_person
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.leads.filters import FilterSet, SortDirection, SortField
from app.leads.search import search_leads
from app.leads.search_schemas import MAX_PAGE_SIZE, SearchRequest

TAG = "Pagination Test Industry"
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _tagged_leads(db: Session, count: int) -> list:
    """Create `count` leads at companies in the test industry, with distinct names and times."""
    leads = []
    for index in range(count):
        company = make_company(db, industry=TAG, name=f"Company {chr(ord('a') + index)}")
        leads.append(
            make_person(
                db,
                company_id=company.id,
                first_name=f"First{index}",
                last_name=f"Last{chr(ord('a') + index)}",
                title=f"Title {chr(ord('z') - index)}",
                last_contacted_at=BASE + timedelta(days=index) if index % 2 == 0 else None,
            )
        )
    return leads


def _search(db: Session, **kwargs: object):
    """Search the tagged industry with the given sort/paging arguments."""
    return search_leads(db, FilterSet(industries=[TAG]), **kwargs)


def test_total_counts_all_matches_not_only_the_page(db_session: Session) -> None:
    """With 5 matches and limit 2, the page has 2 rows and total is 5."""
    _tagged_leads(db_session, 5)

    response = _search(db_session, limit=2, offset=0)

    assert len(response.items) == 2 and response.total == 5
    assert (response.limit, response.offset) == (2, 0)


def test_pages_do_not_repeat_or_skip_rows(db_session: Session) -> None:
    """Walking offset 0, 2, 4 returns every lead exactly once, in a stable order."""
    leads = _tagged_leads(db_session, 5)

    seen = []
    for offset in (0, 2, 4):
        seen += [row.person_id for row in _search(db_session, limit=2, offset=offset).items]

    assert sorted(seen, key=str) == sorted((lead.id for lead in leads), key=str)
    assert len(seen) == len(set(seen))


def test_offset_past_the_end_returns_empty_page_with_total(db_session: Session) -> None:
    """An offset beyond the last row gives no items but the right total."""
    _tagged_leads(db_session, 3)

    response = _search(db_session, limit=10, offset=50)

    assert response.items == [] and response.total == 3


def test_ties_are_broken_by_id_so_pages_are_stable(db_session: Session) -> None:
    """Leads with identical sort values keep one fixed order across repeated searches."""
    company = make_company(db_session, industry=TAG)
    for _ in range(6):
        make_person(db_session, company_id=company.id, first_name="Same", last_name="Same")

    first = [r.person_id for r in _search(db_session, limit=6, offset=0).items]
    second = [r.person_id for r in _search(db_session, limit=6, offset=0).items]

    assert first == second


@pytest.mark.parametrize(
    ("sort", "key"),
    [
        (SortField.NAME, lambda row: (row.last_name or "").lower()),
        (SortField.COMPANY, lambda row: row.company.name.lower()),
        (SortField.TITLE, lambda row: (row.title or "").lower()),
    ],
)
def test_sort_ascending_and_descending(db_session: Session, sort: SortField, key) -> None:
    """Name, company and title sort case-insensitively in both directions."""
    _tagged_leads(db_session, 4)

    ascending = _search(db_session, sort=sort, direction=SortDirection.ASC, limit=10, offset=0)
    descending = _search(db_session, sort=sort, direction=SortDirection.DESC, limit=10, offset=0)

    assert [key(r) for r in ascending.items] == sorted(key(r) for r in ascending.items)
    assert [key(r) for r in descending.items] == sorted(
        (key(r) for r in descending.items), reverse=True
    )


def test_sort_by_last_contacted_puts_never_contacted_last(db_session: Session) -> None:
    """Leads never contacted sort after contacted ones, whichever the direction."""
    _tagged_leads(db_session, 4)  # indexes 0 and 2 have a date, 1 and 3 do not

    for direction in (SortDirection.ASC, SortDirection.DESC):
        rows = _search(
            db_session, sort=SortField.LAST_CONTACTED_AT, direction=direction, limit=10, offset=0
        ).items
        dates = [row.last_contacted_at for row in rows]
        assert dates[:2] == sorted([d for d in dates if d], reverse=direction is SortDirection.DESC)
        assert dates[2:] == [None, None]


def test_sort_by_created_at_is_accepted(db_session: Session) -> None:
    """created_at is a valid sort field and returns every match."""
    _tagged_leads(db_session, 3)

    response = _search(db_session, sort=SortField.CREATED_AT, limit=10, offset=0)

    assert len(response.items) == 3


def test_request_rejects_unsupported_sort_and_bad_paging() -> None:
    """An unknown sort, a limit of 0 or over the maximum, or a negative offset is rejected."""
    for bad in (
        {"sort": "salary"},
        {"limit": 0},
        {"limit": MAX_PAGE_SIZE + 1},
        {"offset": -1},
        {"direction": "sideways"},
    ):
        with pytest.raises(ValidationError):
            SearchRequest.model_validate(bad)
    assert SearchRequest().limit == 50 and SearchRequest().sort is SortField.NAME
    assert SearchRequest(limit=MAX_PAGE_SIZE).limit == MAX_PAGE_SIZE
