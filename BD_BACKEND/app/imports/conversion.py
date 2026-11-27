"""Convert one spreadsheet cell to the JSON type of its target field (type conversion only).

Needed so the preview and the import pipeline hand W2 values of the right JSON type (number,
true/false, ISO date) whichever source the file came from. This module changes the type, never
the meaning: it does not normalize emails, names, countries or industries (that is W2's job,
module C), and it never guesses: a cell it cannot read becomes None plus a warning code, so
the row is still delivered and W2 decides what a missing value means (D-068).
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.leads.contracts import FieldType, JsonScalar

# Warning codes shown in the preview and counted in the estimate.
WARNING_NOT_AN_INTEGER = "not_an_integer"
WARNING_NOT_A_NUMBER = "not_a_number"
WARNING_NOT_A_BOOLEAN = "not_a_boolean"
WARNING_NOT_A_DATE = "not_a_date"

_TRUE_WORDS = frozenset({"true", "yes", "y", "t", "1"})
_FALSE_WORDS = frozenset({"false", "no", "n", "f", "0"})
# Optional sign, digits with optional "," thousands groups, optional fraction.
_PLAIN_NUMBER = re.compile(r"[+-]?\d+(\.\d+)?")


class FieldFormat(BaseModel):
    """Optional per-field parsing hints declared by a source profile (D-040).

    Attributes:
        decimal_separator: "," for sources that write 1.234,56; the default "." otherwise.
        date_format: A strptime pattern for dates that are not ISO-8601, such as "%d/%m/%Y".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    decimal_separator: Literal[".", ","] = "."
    date_format: str | None = None


DEFAULT_FORMAT = FieldFormat()


@dataclass(frozen=True, slots=True)
class Converted:
    """The result of converting one cell: the value (None if blank or unreadable) and a warning."""

    value: JsonScalar
    warning: str | None = None


def is_blank(cell: object) -> bool:
    """True for an empty cell: None, or text with only whitespace."""
    return cell is None or (isinstance(cell, str) and not cell.strip())


def _as_text(cell: object) -> str:
    """Cell as trimmed text; a whole-number float (Excel stores 5 as 5.0) prints without ".0"."""
    if isinstance(cell, float) and cell.is_integer():
        return str(int(cell))
    if isinstance(cell, datetime | date):
        return cell.isoformat()
    return str(cell).strip()


def _plain_number_text(text: str, fmt: FieldFormat) -> str | None:
    """Rewrite a number as plain digits with "." as the decimal point, or None if it is not one."""
    if fmt.decimal_separator == ",":
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    text = text.replace(" ", "")
    return text if _PLAIN_NUMBER.fullmatch(text) else None


def _convert_integer(cell: object, fmt: FieldFormat) -> Converted:
    """Whole numbers only: 1,200 and 12.0 are accepted, 12.5 and "many" are not."""
    if isinstance(cell, bool):
        return Converted(None, WARNING_NOT_AN_INTEGER)
    if isinstance(cell, int):
        return Converted(cell)
    text = _plain_number_text(_as_text(cell), fmt)
    if text is None:
        return Converted(None, WARNING_NOT_AN_INTEGER)
    number = float(text)
    if not number.is_integer():
        return Converted(None, WARNING_NOT_AN_INTEGER)
    return Converted(int(number))


def _convert_decimal(cell: object, fmt: FieldFormat) -> Converted:
    """Numbers with an optional fraction; no currency symbols or "5M" shorthand are guessed."""
    if isinstance(cell, bool):
        return Converted(None, WARNING_NOT_A_NUMBER)
    if isinstance(cell, int | float):
        return Converted(float(cell))
    text = _plain_number_text(_as_text(cell), fmt)
    if text is None:
        return Converted(None, WARNING_NOT_A_NUMBER)
    return Converted(float(text))


def _convert_boolean(cell: object) -> Converted:
    """true/yes/y/t/1 and false/no/n/f/0, in any letter case."""
    if isinstance(cell, bool):
        return Converted(cell)
    word = _as_text(cell).casefold()
    if word in _TRUE_WORDS:
        return Converted(True)
    if word in _FALSE_WORDS:
        return Converted(False)
    return Converted(None, WARNING_NOT_A_BOOLEAN)


def _convert_datetime(cell: object, fmt: FieldFormat) -> Converted:
    """Return an ISO-8601 string (W2 attaches the time zone, so none is added here)."""
    if isinstance(cell, datetime | date):
        return Converted(cell.isoformat())
    text = _as_text(cell)
    try:
        if fmt.date_format is not None:
            return Converted(datetime.strptime(text, fmt.date_format).isoformat())
        return Converted(datetime.fromisoformat(text).isoformat())
    except ValueError:
        return Converted(None, WARNING_NOT_A_DATE)


def convert_cell(
    cell: object, value_type: FieldType, fmt: FieldFormat = DEFAULT_FORMAT
) -> Converted:
    """Convert one cell to the JSON type of its target field.

    Args:
        cell: The value as read from the file (text for CSV; text, number, bool or date for XLSX).
        value_type: The target field's type from the registry.
        fmt: The profile's parsing hints for this field.

    Returns:
        The converted value, or None with a warning code when the cell cannot be read. A blank
        cell gives None and no warning.
    """
    if is_blank(cell):
        return Converted(None)
    if value_type is FieldType.TEXT:
        return Converted(_as_text(cell))
    if value_type is FieldType.INTEGER:
        return _convert_integer(cell, fmt)
    if value_type is FieldType.DECIMAL:
        return _convert_decimal(cell, fmt)
    if value_type is FieldType.BOOLEAN:
        return _convert_boolean(cell)
    return _convert_datetime(cell, fmt)
