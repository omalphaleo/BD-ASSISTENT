"""Tests for the shared CSV formula-injection guard (core.csv_safety).

Needed because both the import downloads and the lead export rely on it: a cell that starts with
a formula character must never reach a spreadsheet as a formula. Moved here from the import
report tests when the helper moved to core (M3-A5). Pure functions, no database.
"""

import csv
import io

import pytest

from app.core.csv_safety import csv_text, neutralise_cell


@pytest.mark.parametrize("risky", ["=1+1", "+1", "-1", "@SUM(A1)", "\tcmd", "\rcmd"])
def test_formula_characters_get_a_leading_apostrophe(risky: str) -> None:
    """A cell starting with = + - @ tab or CR is written as text, never as a formula."""
    assert neutralise_cell(risky) == "'" + risky


def test_plain_cells_are_left_alone() -> None:
    """Ordinary text, empty cells and None are written unchanged (None as empty)."""
    assert neutralise_cell("Ada") == "Ada"
    assert neutralise_cell("a=b") == "a=b"
    assert neutralise_cell(None) == ""
    assert neutralise_cell(7) == "7"


def test_csv_text_neutralises_header_and_body_and_uses_crlf() -> None:
    """Header and body cells are both neutralised and lines end with CRLF."""
    text = csv_text(["=name", "ok"], [["@x", "a,b"], [None, 3]])
    assert text.endswith("\r\n")
    assert text.count("\r\n") == 3
    assert list(csv.reader(io.StringIO(text))) == [["'=name", "ok"], ["'@x", "a,b"], ["", "3"]]
