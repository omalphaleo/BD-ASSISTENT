"""CSV cell neutralisation against spreadsheet formula injection, plus a safe CSV writer.

Needed because every CSV the app lets people download (import reports, lead search export)
holds text that came from outside; a cell starting with = + - @ tab or CR would run as a formula
when opened in Excel. Lives in core so imports and leads both use one implementation without
importing each other.
"""

import csv
import io
from collections.abc import Iterable, Sequence

# Characters that make a spreadsheet read a cell as a formula (OWASP CSV injection).
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
FORMULA_ESCAPE = "'"


def neutralise_cell(value: object) -> str:
    """Return a cell as text that a spreadsheet will not run as a formula.

    A text that starts with a formula character gets a leading apostrophe, which spreadsheets
    hide and treat as "this is text". None becomes an empty cell. Numbers and booleans are
    written with str(), so a negative number such as -5 also gets the apostrophe: a harmless
    price for never having to guess which "-" is a formula.
    """
    if value is None:
        return ""
    text = str(value)
    if text.startswith(FORMULA_PREFIXES):
        return FORMULA_ESCAPE + text
    return text


def csv_text(header: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    """Write a header and rows as CSV text (CRLF lines), neutralising every cell, header too."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([neutralise_cell(cell) for cell in header])
    for row in rows:
        writer.writerow([neutralise_cell(cell) for cell in row])
    return buffer.getvalue()
