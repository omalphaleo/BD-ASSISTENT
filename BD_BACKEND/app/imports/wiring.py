"""The only place W1 (imports) reaches W2's real ingest_row.

Needed so the pipeline never imports leads/ingest.py directly: tests hand it a fake, and at
integration step I1 (M2-A7) this file is changed in one line to return the real function.
Until then the stub fails loudly, so an unwired import cannot silently report fake results.
"""

from sqlalchemy.orm import Session

from app.leads.contracts import ImportContext, IngestRow, RowOutcome, SourceRow


def _unwired_ingest_row(session: Session, row: SourceRow, ctx: ImportContext) -> RowOutcome:
    """Stand-in for W2's ingest_row until step I1.

    Raises:
        NotImplementedError: Always, because the real function is not connected yet.
    """
    raise NotImplementedError("ingest_row is not wired yet (M2-A7 integration step I1)")


def get_ingest_row() -> IngestRow:
    """Return the ingest_row the pipeline should call (currently the failing stub)."""
    return _unwired_ingest_row
