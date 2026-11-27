"""Tests for the idempotent mapping seed in app.leads.seed_reference_data (M2-B1).

Needed because the industry and state mapping tables start empty and normalization relies on
them; the seed must fill them, must be safe to run twice, and must never overwrite a row BD
has edited. Runs on real PostgreSQL inside the rolled-back db_session fixture.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.leads.models import IndustryMapping, StateMapping
from app.leads.normalization import STANDARD_INDUSTRY_MAP
from app.leads.reference_data import US_STATES
from app.leads.seed_reference_data import seed_reference_data


def _count(session: Session, model: type[IndustryMapping | StateMapping]) -> int:
    """Count the rows of one mapping table."""
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_seed_fills_both_tables(db_session: Session) -> None:
    """The first run adds every starter industry wording and each US state twice."""
    result = seed_reference_data(db_session)

    assert result.industry_mappings_added == len(STANDARD_INDUSTRY_MAP)
    assert result.state_mappings_added == len(US_STATES) * 2
    assert _count(db_session, IndustryMapping) == len(STANDARD_INDUSTRY_MAP)
    assert _count(db_session, StateMapping) == len(US_STATES) * 2


def test_seed_is_idempotent(db_session: Session) -> None:
    """A second run adds nothing and leaves the row counts unchanged."""
    seed_reference_data(db_session)
    before = (_count(db_session, IndustryMapping), _count(db_session, StateMapping))

    result = seed_reference_data(db_session)

    assert (result.industry_mappings_added, result.state_mappings_added) == (0, 0)
    assert (_count(db_session, IndustryMapping), _count(db_session, StateMapping)) == before


def test_seed_does_not_overwrite_an_edited_mapping(db_session: Session) -> None:
    """A mapping BD changed keeps its value when the seed runs again."""
    seed_reference_data(db_session)
    software = db_session.scalars(
        select(IndustryMapping).where(IndustryMapping.source_name == "software")
    ).one()
    software.standard_industry = "Edited By BD"
    db_session.flush()

    seed_reference_data(db_session)

    db_session.refresh(software)
    assert software.standard_industry == "Edited By BD"


def test_seeded_rows_carry_sector_codes_and_abbreviations(db_session: Session) -> None:
    """Seeded rows keep the NAICS sector code and the state abbreviation."""
    seed_reference_data(db_session)

    software = db_session.scalars(
        select(IndustryMapping).where(IndustryMapping.source_name == "software")
    ).one()
    texas = db_session.scalars(select(StateMapping).where(StateMapping.source_value == "tx")).one()

    assert (software.standard_industry, software.naics_sector) == ("Information", "51")
    assert (texas.standard_name, texas.abbreviation, texas.country) == (
        "Texas",
        "TX",
        "United States",
    )
