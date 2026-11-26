"""Read an uploaded CSV or XLSX file: validate its format, find headers and count data rows.

Needed so the upload service can refuse unusable files (D-110: CSV or XLSX, 20 MB, 50,000
rows, one sheet per import) before anything is stored, and so later steps (mapping, the import
pipeline) know the file's headers and size. Only non-empty data rows count toward the row limit;
the header row and blank rows do not. This module reads structure only: it never maps columns
or judges lead data, and it never extracts an archive to disk.
"""

import csv
import enum
import io
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import BinaryIO
from xml.etree.ElementTree import ParseError

from defusedxml import DefusedXmlException
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.config import Settings
from app.imports.errors import UploadErrorKind, UploadRejectedError
from app.imports.xlsx_safety import ZipLimits, check_xlsx_archive

# Delimiters tried for CSV files (comma and semicolon only; others are rejected as unknown).
CSV_DELIMITERS = (",", ";")
# Header record plus up to 20 data records are compared to decide between two delimiters.
CSV_SAMPLE_RECORDS = 21
# Fewer than this many header cells means "no delimiter found": a single-column file.
MIN_CSV_COLUMNS = 2

UNSUPPORTED_MESSAGE = "Only .csv and .xlsx files can be imported."
ENCODING_MESSAGE = "The CSV file must be UTF-8 or Windows-1252 text."
BINARY_MESSAGE = "The file contains binary data and is not a text CSV file."
CSV_MALFORMED_MESSAGE = "The CSV file could not be read."
AMBIGUOUS_MESSAGE = (
    "The CSV delimiter could not be determined. Use a comma or semicolon and at least two columns."
)
EMPTY_MESSAGE = "The file has no data rows."
XLSX_MALFORMED_MESSAGE = "The XLSX file could not be read."
BAD_WORKSHEET_MESSAGE = "That worksheet does not exist in the file."


class FileFormat(enum.StrEnum):
    """The two accepted upload formats; the value doubles as the storage key extension."""

    CSV = "csv"
    XLSX = "xlsx"


@dataclass(frozen=True, slots=True)
class UploadLimits:
    """All bounds applied to an upload (built from Settings)."""

    max_bytes: int
    max_rows: int
    zip: ZipLimits


@dataclass(frozen=True, slots=True)
class WorksheetInfo:
    """One worksheet of an XLSX file as shown to the user.

    row_count is the number of non-empty data rows below the header; when a sheet exceeds the
    limit counting stops, so it is reported as max_rows + 1 and is not selectable.
    """

    name: str
    row_count: int
    selectable: bool


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """What the upload service learns about a file.

    For CSV: row_count and headers are set and worksheets is empty. For XLSX with several
    sheets: worksheets is set and the user must pick one (row_count and headers are None).
    For XLSX with one sheet: that sheet is selected, so selected_worksheet, row_count and
    headers are set.
    """

    file_format: FileFormat
    row_count: int | None
    headers: tuple[str, ...] | None
    worksheets: tuple[WorksheetInfo, ...]
    selected_worksheet: str | None


def limits_from_settings(settings: Settings) -> UploadLimits:
    """Build the UploadLimits from the application settings."""
    return UploadLimits(
        max_bytes=settings.upload_max_bytes,
        max_rows=settings.upload_max_rows,
        zip=ZipLimits(
            max_entries=settings.xlsx_max_entries,
            max_member_bytes=settings.xlsx_max_member_bytes,
            max_total_bytes=settings.xlsx_max_total_bytes,
            max_compression_ratio=settings.xlsx_max_compression_ratio,
        ),
    )


def detect_format(filename: str) -> FileFormat:
    """Choose the format from the file name's extension (case-insensitive).

    Raises:
        UploadRejectedError: UNSUPPORTED_TYPE for any other extension (including .xls).
    """
    lowered = filename.lower()
    for file_format in FileFormat:
        if lowered.endswith(f".{file_format.value}"):
            return file_format
    raise UploadRejectedError(UploadErrorKind.UNSUPPORTED_TYPE, UNSUPPORTED_MESSAGE)


def parse_upload(source: BinaryIO, file_format: FileFormat, limits: UploadLimits) -> ParsedFile:
    """Validate an uploaded file and describe it.

    Args:
        source: Seekable binary file with the complete upload.
        file_format: The format chosen by detect_format().
        limits: The configured bounds.

    Raises:
        UploadRejectedError: If the file is malformed, ambiguous, empty, unsafe or over a limit.
    """
    if file_format is FileFormat.CSV:
        return _parse_csv(source, limits)
    return _parse_xlsx(source, limits)


def count_worksheet(source: BinaryIO, worksheet_name: str, limits: UploadLimits) -> WorksheetInfo:
    """Count the data rows of one worksheet of an already stored XLSX file.

    Raises:
        UploadRejectedError: BAD_WORKSHEET if the name is not in the file; otherwise the same
            errors as parse_upload() for an unsafe or unreadable archive.
    """
    check_xlsx_archive(source, limits.zip)
    with _open_workbook(source) as workbook:
        if worksheet_name not in workbook.sheetnames:
            raise UploadRejectedError(UploadErrorKind.BAD_WORKSHEET, BAD_WORKSHEET_MESSAGE)
        _, info = _scan_worksheet(workbook[worksheet_name], limits.max_rows)
    return info


def read_worksheet_headers(
    source: BinaryIO, worksheet_name: str, limits: UploadLimits
) -> tuple[str, ...]:
    """Return the header cells of one worksheet of a stored XLSX file (empty cells as '')."""
    check_xlsx_archive(source, limits.zip)
    with _open_workbook(source) as workbook:
        if worksheet_name not in workbook.sheetnames:
            raise UploadRejectedError(UploadErrorKind.BAD_WORKSHEET, BAD_WORKSHEET_MESSAGE)
        headers, _ = _scan_worksheet(workbook[worksheet_name], limits.max_rows)
    return headers


# --- CSV -------------------------------------------------------------------------------------


def _is_blank(cells: list[str]) -> bool:
    """True for a record with no cells or only empty or whitespace cells."""
    return all(not cell.strip() for cell in cells)


def _decode_csv(data: bytes) -> str:
    """Decode as UTF-8 (BOM allowed), else Windows-1252; reject anything else.

    A file that is valid UTF-8 is always read as UTF-8. Windows-1252 leaves five bytes
    undefined, so a corrupt file still fails here instead of being read as garbage.

    Raises:
        UploadRejectedError: MALFORMED_FILE for NUL bytes (binary or UTF-16) or undecodable text.
    """
    if b"\x00" in data:
        raise UploadRejectedError(UploadErrorKind.MALFORMED_FILE, BINARY_MESSAGE)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise UploadRejectedError(UploadErrorKind.MALFORMED_FILE, ENCODING_MESSAGE) from exc


def _sample_records(text: str, delimiter: str) -> list[list[str]]:
    """Return the first CSV_SAMPLE_RECORDS non-blank records read with this delimiter."""
    records: list[list[str]] = []
    try:
        for record in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
            if _is_blank(record):
                continue
            records.append(record)
            if len(records) >= CSV_SAMPLE_RECORDS:
                break
    except csv.Error as exc:
        raise UploadRejectedError(UploadErrorKind.MALFORMED_FILE, CSV_MALFORMED_MESSAGE) from exc
    return records


def _choose_delimiter(text: str) -> str:
    """Pick comma or semicolon, or refuse when the choice is not clear (never guess).

    The delimiter "appears" when the header splits into two or more cells with it. If both
    appear, the one that gives every sampled data row the header's cell count wins; a tie or
    no winner is ambiguous. A header with neither is a single-column file, which is rejected.

    Raises:
        UploadRejectedError: EMPTY_FILE for a file with no records, AMBIGUOUS_CSV otherwise.
    """
    samples = {delimiter: _sample_records(text, delimiter) for delimiter in CSV_DELIMITERS}
    if not samples[CSV_DELIMITERS[0]]:
        raise UploadRejectedError(UploadErrorKind.EMPTY_FILE, EMPTY_MESSAGE)
    appearing = [d for d in CSV_DELIMITERS if len(samples[d][0]) >= MIN_CSV_COLUMNS]
    if len(appearing) == 1:
        return appearing[0]
    consistent = [
        d for d in appearing if all(len(row) == len(samples[d][0]) for row in samples[d][1:])
    ]
    if len(consistent) == 1:
        return consistent[0]
    raise UploadRejectedError(UploadErrorKind.AMBIGUOUS_CSV, AMBIGUOUS_MESSAGE)


def _parse_csv(source: BinaryIO, limits: UploadLimits) -> ParsedFile:
    """Decode, choose the delimiter, read headers and count non-empty data rows."""
    text = _decode_csv(source.read(limits.max_bytes + 1))
    delimiter = _choose_delimiter(text)
    headers: tuple[str, ...] | None = None
    row_count = 0
    try:
        for record in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
            if _is_blank(record):
                continue
            if headers is None:
                headers = tuple(cell.strip() for cell in record)
                continue
            row_count += 1
            if row_count > limits.max_rows:
                raise UploadRejectedError(UploadErrorKind.TOO_MANY_ROWS, _too_many_message(limits))
    except csv.Error as exc:
        raise UploadRejectedError(UploadErrorKind.MALFORMED_FILE, CSV_MALFORMED_MESSAGE) from exc
    if row_count == 0:
        raise UploadRejectedError(UploadErrorKind.EMPTY_FILE, EMPTY_MESSAGE)
    return ParsedFile(FileFormat.CSV, row_count, headers, (), None)


def _too_many_message(limits: UploadLimits) -> str:
    """Fixed row-limit message that states the configured limit."""
    return f"The file has more than {limits.max_rows:,} data rows."


# --- XLSX ------------------------------------------------------------------------------------


@contextmanager
def _open_workbook(source: BinaryIO) -> Iterator[Workbook]:
    """Open an XLSX read-only, yield the workbook and always close it afterwards.

    openpyxl raises many different exception types on hostile or damaged files, so opening is
    wrapped once here and every one of them becomes the same user-facing MALFORMED_FILE error.

    Raises:
        UploadRejectedError: MALFORMED_FILE if openpyxl cannot read the file.
    """
    source.seek(0)
    try:
        # read_only streams the sheet XML; data_only returns cached formula results and never
        # evaluates a formula.
        workbook = load_workbook(source, read_only=True, data_only=True)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        zipfile.BadZipFile,
        InvalidFileException,
        ParseError,
        DefusedXmlException,
    ) as exc:
        raise UploadRejectedError(UploadErrorKind.MALFORMED_FILE, XLSX_MALFORMED_MESSAGE) from exc
    try:
        yield workbook
    finally:
        workbook.close()
        source.seek(0)


def _cell_text(value: object) -> str:
    """Header cell as trimmed text; an empty cell becomes ''."""
    return "" if value is None else str(value).strip()


def _scan_worksheet(sheet: Worksheet, max_rows: int) -> tuple[tuple[str, ...], WorksheetInfo]:
    """Read one sheet's header and count its non-empty data rows, stopping past the limit.

    The first non-empty row is the header. read_only sheets can report a wrong size, so rows
    are simply iterated; counting stops at max_rows + 1 so a huge sheet costs little.
    """
    headers: tuple[str, ...] | None = None
    count = 0
    try:
        for row in sheet.iter_rows(values_only=True):
            cells = [_cell_text(value) for value in row]
            if _is_blank(cells):
                continue
            if headers is None:
                headers = tuple(cells)
                continue
            count += 1
            if count > max_rows:
                break
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        ParseError,
        DefusedXmlException,
    ) as exc:
        raise UploadRejectedError(UploadErrorKind.MALFORMED_FILE, XLSX_MALFORMED_MESSAGE) from exc
    selectable = 0 < count <= max_rows
    return headers or (), WorksheetInfo(sheet.title, count, selectable)


def _parse_xlsx(source: BinaryIO, limits: UploadLimits) -> ParsedFile:
    """Check the archive, then list every worksheet with its data-row count.

    Raises:
        UploadRejectedError: If no sheet is usable (all empty, or all over the row limit).
    """
    check_xlsx_archive(source, limits.zip)
    infos: list[WorksheetInfo] = []
    first_headers: dict[str, tuple[str, ...]] = {}
    with _open_workbook(source) as workbook:
        for name in workbook.sheetnames:
            headers, info = _scan_worksheet(workbook[name], limits.max_rows)
            infos.append(info)
            first_headers[name] = headers
    selectable = [info for info in infos if info.selectable]
    if not selectable:
        if any(info.row_count > limits.max_rows for info in infos):
            raise UploadRejectedError(UploadErrorKind.TOO_MANY_ROWS, _too_many_message(limits))
        raise UploadRejectedError(UploadErrorKind.EMPTY_FILE, EMPTY_MESSAGE)
    if len(infos) == 1:
        only = infos[0]
        return ParsedFile(
            FileFormat.XLSX, only.row_count, first_headers[only.name], tuple(infos), only.name
        )
    return ParsedFile(FileFormat.XLSX, None, None, tuple(infos), None)
