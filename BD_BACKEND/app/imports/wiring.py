"""The only place W1 (imports) reaches W2's real ingest_row.

Needed so the pipeline never imports leads/ingest.py directly: tests hand it a fake, and the
process_import task asks this file for the real function (integration step I1, M2-A7). Keeping
the one import here means the module dependency test can allow exactly one edge from imports
into leads.ingest, and swapping the function stays a one-line change.
"""

from app.leads.contracts import IngestRow
from app.leads.ingest import ingest_row


def get_ingest_row() -> IngestRow:
    """Return the ingest_row the pipeline should call: W2's real implementation."""
    return ingest_row
