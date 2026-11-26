"""Tests for the CSV and XLSX parsers and the XLSX archive safety checks (M2-A1, D-110).

Needed because the parsers decide which uploads are accepted: the encoding and delimiter
rules, the "non-empty data rows only" count, the 50,000-row limit and the ZIP bomb guards
must hold exactly as agreed. No database; every file is built in memory from synthetic rows.
"""

import io
import zipfile
from dataclasses import replace

import pytest
from import_files import HEADER, csv_bytes, sample_csv, sheet_rows, xlsx_bytes

from app.imports import xlsx_safety
from app.imports.errors import UploadErrorKind, UploadRejectedError
from app.imports.parsers import (
    FileFormat,
    UploadLimits,
    count_worksheet,
    detect_format,
    parse_upload,
    read_worksheet_headers,
)
from app.imports.xlsx_safety import ZipLimits, check_xlsx_archive

ZIP_LIMITS = ZipLimits(
    max_entries=1000,
    max_member_bytes=100 * 1024 * 1024,
    max_total_bytes=200 * 1024 * 1024,
    max_compression_ratio=100,
)
LIMITS = UploadLimits(max_bytes=20 * 1024 * 1024, max_rows=50_000, zip=ZIP_LIMITS)
SMALL = replace(LIMITS, max_rows=3)


def _parse_csv(data: bytes, limits: UploadLimits = LIMITS):
    """Parse bytes as a CSV upload."""
    return parse_upload(io.BytesIO(data), FileFormat.CSV, limits)


def _parse_xlsx(data: bytes, limits: UploadLimits = LIMITS):
    """Parse bytes as an XLSX upload."""
    return parse_upload(io.BytesIO(data), FileFormat.XLSX, limits)


def _refused(kind: UploadErrorKind):
    """Context manager expecting UploadRejectedError of one kind."""
    return pytest.raises(UploadRejectedError, check=lambda e: e.kind is kind)


# --- format detection ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [("a.csv", FileFormat.CSV), ("A.CSV", FileFormat.CSV), ("b.XLSX", FileFormat.XLSX)],
)
def test_detect_format_accepts_csv_and_xlsx_in_any_case(name: str, expected: FileFormat) -> None:
    """The extension decides the format, ignoring case."""
    assert detect_format(name) is expected


@pytest.mark.parametrize("name", ["old.xls", "doc.pdf", "noextension", "x.csv.exe"])
def test_detect_format_refuses_other_types(name: str) -> None:
    """Anything but .csv and .xlsx (including legacy .xls) is UNSUPPORTED_TYPE."""
    with _refused(UploadErrorKind.UNSUPPORTED_TYPE):
        detect_format(name)


# --- CSV: encoding ---------------------------------------------------------------------------


def test_csv_utf8_reads_headers_and_counts_data_rows() -> None:
    """A plain UTF-8 comma file gives its headers and the number of data rows."""
    parsed = _parse_csv(sample_csv(data_rows=3))
    assert parsed.file_format is FileFormat.CSV
    assert parsed.row_count == 3
    assert parsed.headers == tuple(HEADER)
    assert parsed.worksheets == ()


def test_csv_utf8_bom_is_stripped_from_the_first_header() -> None:
    """A UTF-8 BOM does not end up in the first header name."""
    parsed = _parse_csv(csv_bytes([HEADER, ["a", "b", "c@example.com"]], bom=True))
    assert parsed.headers is not None and parsed.headers[0] == "First Name"


def test_csv_windows_1252_is_decoded() -> None:
    """A Windows-1252 file (not valid UTF-8) is read with accented headers intact."""
    data = csv_bytes(
        [["Prénom", "Nom", "Email"], ["Zoë", "Müller", "z@example.com"]], encoding="cp1252"
    )
    with pytest.raises(UnicodeDecodeError):
        data.decode("utf-8")  # proves the fixture really needs the fallback
    assert _parse_csv(data).headers == ("Prénom", "Nom", "Email")


def test_csv_with_undecodable_bytes_is_refused() -> None:
    """Bytes that are neither UTF-8 nor Windows-1252 (0x81 is undefined in both) are refused."""
    with _refused(UploadErrorKind.MALFORMED_FILE):
        _parse_csv(b"a,b\r\n\x81,\xff\r\n")


def test_csv_with_nul_bytes_is_refused_as_binary() -> None:
    """A UTF-16 or binary file contains NUL bytes and is refused, not misread."""
    with _refused(UploadErrorKind.MALFORMED_FILE):
        _parse_csv("a,b\r\n1,2\r\n".encode("utf-16"))


# --- CSV: delimiter --------------------------------------------------------------------------


def test_csv_semicolon_delimiter_is_detected() -> None:
    """A semicolon file is read with three columns, not one."""
    parsed = _parse_csv(csv_bytes([HEADER, ["a", "b", "c@example.com"]], delimiter=";"))
    assert parsed.headers == tuple(HEADER)


def test_csv_single_column_file_is_refused() -> None:
    """A header with no delimiter is a single-column file and is refused as ambiguous."""
    with _refused(UploadErrorKind.AMBIGUOUS_CSV):
        _parse_csv(b"Email\r\na@example.com\r\nb@example.com\r\n")


def test_csv_with_both_delimiters_fitting_equally_is_ambiguous() -> None:
    """Both comma and semicolon split every row into two cells: refuse instead of guessing."""
    with _refused(UploadErrorKind.AMBIGUOUS_CSV):
        _parse_csv(b"a,b;c\r\n1,2;3\r\n")


def test_csv_with_both_delimiters_picks_the_one_that_is_consistent() -> None:
    """Header has both characters, but only the comma gives every data row the same width."""
    parsed = _parse_csv(b"a;b,c\r\nx,y\r\nz,w\r\n")
    assert parsed.headers == ("a;b", "c")


def test_csv_with_both_delimiters_and_no_consistent_choice_is_ambiguous() -> None:
    """If neither delimiter fits the data rows, the file is refused."""
    with _refused(UploadErrorKind.AMBIGUOUS_CSV):
        _parse_csv(b"a;b,c\r\n1;2;3\r\n")


# --- CSV: counting ---------------------------------------------------------------------------


def test_csv_blank_rows_and_the_header_are_not_counted() -> None:
    """Blank lines and rows of only empty cells do not count toward the row total."""
    data = (
        b"First,Last,Email\r\n\r\nAda,L,a@example.com\r\n,,\r\n   , ,\r\nAlan,T,b@example.com\r\n"
    )
    assert _parse_csv(data).row_count == 2


def test_csv_at_the_row_limit_is_accepted_and_one_over_is_refused() -> None:
    """With a limit of 3, three data rows pass and four are TOO_MANY_ROWS."""
    assert _parse_csv(sample_csv(data_rows=3), SMALL).row_count == 3
    with _refused(UploadErrorKind.TOO_MANY_ROWS):
        _parse_csv(sample_csv(data_rows=4), SMALL)


def test_csv_blank_rows_do_not_push_a_file_over_the_limit() -> None:
    """Many blank rows around three data rows stay within a limit of three."""
    rows = [HEADER] + [["", "", ""]] * 10 + [["a", "b", "c@example.com"]] * 3
    assert _parse_csv(csv_bytes(rows), SMALL).row_count == 3


@pytest.mark.parametrize(
    "data", [b"", b"\r\n\r\n", b"First,Last,Email\r\n", b"First,Last,Email\r\n,,\r\n"]
)
def test_csv_without_data_rows_is_empty(data: bytes) -> None:
    """An empty file, only blank lines, or a header with no data rows is EMPTY_FILE."""
    with _refused(UploadErrorKind.EMPTY_FILE):
        _parse_csv(data)


# --- XLSX: content ---------------------------------------------------------------------------


def test_xlsx_single_sheet_is_selected_automatically() -> None:
    """A workbook with one sheet selects it and reports its headers and row count."""
    parsed = _parse_xlsx(xlsx_bytes({"Leads": sheet_rows(3)}))
    assert parsed.selected_worksheet == "Leads"
    assert parsed.row_count == 3
    assert parsed.headers == tuple(HEADER)
    assert [(w.name, w.row_count, w.selectable) for w in parsed.worksheets] == [("Leads", 3, True)]


def test_xlsx_multi_sheet_lists_each_sheet_and_needs_a_choice() -> None:
    """Several sheets are listed with their counts; none is selected yet."""
    parsed = _parse_xlsx(xlsx_bytes({"A": sheet_rows(2), "B": sheet_rows(1)}))
    assert parsed.selected_worksheet is None
    assert parsed.row_count is None and parsed.headers is None
    assert [(w.name, w.row_count) for w in parsed.worksheets] == [("A", 2), ("B", 1)]


def test_xlsx_blank_rows_are_not_counted() -> None:
    """Blank rows between and after data rows do not count."""
    rows = [list(HEADER), [None, None, None], ["a", "b", "c@example.com"], ["", " ", None]]
    assert _parse_xlsx(xlsx_bytes({"S": rows})).row_count == 1


def test_xlsx_oversized_sheet_is_listed_but_not_selectable() -> None:
    """A sheet over the limit stays in the list as not selectable while another sheet works."""
    parsed = _parse_xlsx(xlsx_bytes({"Big": sheet_rows(5), "Small": sheet_rows(2)}), SMALL)
    by_name = {w.name: w for w in parsed.worksheets}
    assert by_name["Big"].selectable is False and by_name["Big"].row_count == 4  # stops at limit+1
    assert by_name["Small"].selectable is True


def test_xlsx_with_only_oversized_sheets_is_refused() -> None:
    """If no sheet is within the limit the whole file is TOO_MANY_ROWS."""
    with _refused(UploadErrorKind.TOO_MANY_ROWS):
        _parse_xlsx(xlsx_bytes({"Big": sheet_rows(5)}), SMALL)


def test_xlsx_with_only_empty_sheets_is_refused() -> None:
    """A workbook whose sheets have no data rows is EMPTY_FILE."""
    with _refused(UploadErrorKind.EMPTY_FILE):
        _parse_xlsx(xlsx_bytes({"Empty": [list(HEADER)]}))


def test_count_worksheet_and_headers_for_a_chosen_sheet() -> None:
    """The chosen sheet is counted again, and its headers can be read."""
    data = xlsx_bytes({"A": sheet_rows(2), "B": sheet_rows(1)})
    info = count_worksheet(io.BytesIO(data), "B", LIMITS)
    assert (info.name, info.row_count, info.selectable) == ("B", 1, True)
    assert read_worksheet_headers(io.BytesIO(data), "B", LIMITS) == tuple(HEADER)


def test_count_worksheet_refuses_an_unknown_sheet() -> None:
    """Choosing a sheet name that is not in the workbook is BAD_WORKSHEET."""
    with _refused(UploadErrorKind.BAD_WORKSHEET):
        count_worksheet(io.BytesIO(xlsx_bytes({"A": sheet_rows(1)})), "Nope", LIMITS)


# --- XLSX: archive safety --------------------------------------------------------------------


def test_text_pretending_to_be_xlsx_is_refused_as_malformed() -> None:
    """A file that is not a ZIP at all is MALFORMED_FILE."""
    with _refused(UploadErrorKind.MALFORMED_FILE):
        _parse_xlsx(sample_csv())


def test_office_encrypted_workbook_is_refused() -> None:
    """A password-protected workbook is an OLE2 container, not a ZIP, and is refused."""
    ole2_header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600
    with _refused(UploadErrorKind.MALFORMED_FILE):
        _parse_xlsx(ole2_header)


def _zip_with(members: dict[str, bytes]) -> io.BytesIO:
    """Build a ZIP archive from name-to-bytes members."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer


def test_zip_without_a_workbook_part_is_refused() -> None:
    """A valid ZIP that is not a workbook (no xl/workbook.xml) is MALFORMED_FILE."""
    with _refused(UploadErrorKind.MALFORMED_FILE):
        check_xlsx_archive(_zip_with({"hello.txt": b"hi"}), ZIP_LIMITS)


def test_zip_with_too_many_entries_is_unsafe() -> None:
    """More entries than the limit is UNSAFE_ARCHIVE."""
    archive = _zip_with({"xl/workbook.xml": b"<x/>", "a": b"1", "b": b"2"})
    with _refused(UploadErrorKind.UNSAFE_ARCHIVE):
        check_xlsx_archive(archive, replace(ZIP_LIMITS, max_entries=2))


def test_zip_with_an_oversized_member_is_unsafe() -> None:
    """One member larger than the per-member limit is UNSAFE_ARCHIVE."""
    archive = _zip_with({"xl/workbook.xml": b"<x/>", "big.xml": b"A" * 50})
    with _refused(UploadErrorKind.UNSAFE_ARCHIVE):
        check_xlsx_archive(archive, replace(ZIP_LIMITS, max_member_bytes=40))


def test_zip_whose_total_size_is_too_large_is_unsafe() -> None:
    """Members that are each fine but together pass the total limit are UNSAFE_ARCHIVE."""
    archive = _zip_with({"xl/workbook.xml": b"A" * 30, "b.xml": b"B" * 30})
    with _refused(UploadErrorKind.UNSAFE_ARCHIVE):
        check_xlsx_archive(archive, replace(ZIP_LIMITS, max_total_bytes=50))


def test_zip_bomb_by_compression_ratio_is_unsafe() -> None:
    """A member of repeated bytes compresses far past 100:1 and is refused (a mini bomb)."""
    archive = _zip_with({"xl/workbook.xml": b"<x/>", "bomb.xml": b"0" * (5 * 1024 * 1024)})
    assert archive.getbuffer().nbytes < 100 * 1024  # really small on disk
    with _refused(UploadErrorKind.UNSAFE_ARCHIVE):
        check_xlsx_archive(archive, ZIP_LIMITS)


def test_encrypted_member_flag_is_unsafe(monkeypatch: pytest.MonkeyPatch) -> None:
    """A member whose directory entry has the encryption flag set is UNSAFE_ARCHIVE."""
    member = zipfile.ZipInfo("xl/workbook.xml")
    member.flag_bits = 0x1

    class FakeZip:
        """Stands in for ZipFile, listing one member that claims to be encrypted."""

        def __init__(self, source: object) -> None:
            pass

        def __enter__(self) -> "FakeZip":
            return self

        def __exit__(self, *exc: object) -> None:
            pass

        def infolist(self) -> list[zipfile.ZipInfo]:
            return [member]

    monkeypatch.setattr(xlsx_safety.zipfile, "ZipFile", FakeZip)
    with _refused(UploadErrorKind.UNSAFE_ARCHIVE):
        check_xlsx_archive(io.BytesIO(b"ignored"), ZIP_LIMITS)


def test_a_normal_workbook_passes_the_archive_check() -> None:
    """A real workbook passes with the default limits and the stream is rewound."""
    source = io.BytesIO(xlsx_bytes({"S": sheet_rows(2)}))
    check_xlsx_archive(source, ZIP_LIMITS)
    assert source.tell() == 0
