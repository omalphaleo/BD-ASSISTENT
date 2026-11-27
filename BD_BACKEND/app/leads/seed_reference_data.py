"""Idempotent seed for the industry and state mapping tables.

Needed because normalization maps source wordings to standard industries (D-076) and US
states (D-078), and the two mapping tables start empty (the migrations insert no rows).
Running it twice is safe: existing rows are skipped, so BD edits made later (M2-B6) are never
overwritten. Run it once per environment with `python -m app.leads.seed_reference_data`
from BD_BACKEND (in Docker: `docker compose exec api python -m app.leads.seed_reference_data`).
"""

import sys
from dataclasses import dataclass

from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import get_engine
from app.leads.models import IndustryMapping, StateMapping
from app.leads.normalization import STANDARD_INDUSTRY_MAP
from app.leads.reference_data import NAICS_SECTORS, UNITED_STATES, US_STATES


@dataclass(frozen=True, slots=True)
class SeedResult:
    """How many rows one seed run added (zero on a repeat run)."""

    industry_mappings_added: int
    state_mappings_added: int


def _industry_rows() -> list[dict[str, str | None]]:
    """Build the IndustryMapping rows: every sector name and every known alias."""
    sector_code_by_name = {name: code for code, name in NAICS_SECTORS}
    return [
        {
            "source_name": source_name,
            "standard_industry": standard_name,
            "naics_sector": sector_code_by_name[standard_name],
        }
        for source_name, standard_name in STANDARD_INDUSTRY_MAP.items()
    ]


def _state_rows() -> list[dict[str, str | None]]:
    """Build the StateMapping rows: each US state by abbreviation and by full name."""
    rows: list[dict[str, str | None]] = []
    for abbreviation, name in US_STATES.items():
        for source_value in (abbreviation.lower(), name.lower()):
            rows.append(
                {
                    "country": UNITED_STATES,
                    "source_value": source_value,
                    "standard_name": name,
                    "abbreviation": abbreviation,
                }
            )
    return rows


def _insert_missing(
    session: Session,
    model: type[IndustryMapping | StateMapping],
    rows: list[dict[str, str | None]],
) -> int:
    """Insert the rows that do not exist yet (unique-key conflicts are skipped).

    Returns:
        The number of rows actually inserted.
    """
    table = model.__table__
    assert isinstance(table, Table)
    # RETURNING lists only the rows that were really inserted; cursor.rowcount is not
    # reliable for a multi-row ON CONFLICT DO NOTHING insert, so it is not used.
    statement = insert(table).values(rows).on_conflict_do_nothing().returning(table.c.id)
    return len(session.execute(statement).all())


def seed_reference_data(session: Session) -> SeedResult:
    """Add the starter industry and state mappings that are missing; never commits.

    The caller owns the transaction, so a failed run leaves no half-seeded tables.
    """
    return SeedResult(
        industry_mappings_added=_insert_missing(session, IndustryMapping, _industry_rows()),
        state_mappings_added=_insert_missing(session, StateMapping, _state_rows()),
    )


def main() -> int:
    """Seed the configured database and print how many rows were added."""
    with Session(get_engine()) as session:
        result = seed_reference_data(session)
        session.commit()
    print(
        f"Added {result.industry_mappings_added} industry and "
        f"{result.state_mappings_added} state mappings."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
