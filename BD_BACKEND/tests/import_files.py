"""Builders for synthetic CSV, XLSX and multipart upload bodies (a test helper, not a test file).

Needed so the import tests create their input files in memory instead of committing binary
fixtures: every file is built from fake rows, so it is easy to read, change and extend. Used
by test_import_parsers.py, test_import_storage.py and test_import_upload.py.
"""

import csv
import io
from collections.abc import Sequence

from openpyxl import Workbook

# Synthetic rows only: fake names and the reserved example.com domain.
HEADER = ["First Name", "Last Name", "Email"]
ROWS = [
    ["Ada", "Lovelace", "ada@example.com"],
    ["Alan", "Turing", "alan@example.com"],
    ["Grace", "Hopper", "grace@example.com"],
]


def csv_bytes(
    rows: Sequence[Sequence[str]],
    *,
    delimiter: str = ",",
    encoding: str = "utf-8",
    bom: bool = False,
) -> bytes:
    """Render rows as CSV text in the given delimiter and encoding (optionally with a BOM)."""
    buffer = io.StringIO(newline="")
    csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n").writerows(rows)
    data = buffer.getvalue().encode(encoding)
    return (b"\xef\xbb\xbf" + data) if bom else data


def sample_csv(*, data_rows: int = 3) -> bytes:
    """A small valid CSV: a header and data_rows synthetic people."""
    rows = [HEADER] + [
        [f"First{n}", f"Last{n}", f"person{n}@example.com"] for n in range(data_rows)
    ]
    return csv_bytes(rows)


def xlsx_bytes(sheets: dict[str, list[list[object]]]) -> bytes:
    """Build an XLSX workbook with one worksheet per entry (name to rows, header first)."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def sheet_rows(data_rows: int) -> list[list[object]]:
    """A header plus data_rows synthetic people, for xlsx_bytes."""
    return [list(HEADER)] + [
        [f"First{n}", f"Last{n}", f"person{n}@example.com"] for n in range(data_rows)
    ]


def multipart_body(
    filename: str,
    content: bytes,
    *,
    fields: dict[str, str] | None = None,
    boundary: str = "testboundary123",
) -> tuple[bytes, str]:
    """Build a multipart/form-data body with a 'file' part and optional text fields.

    Returns:
        The body bytes and the matching Content-Type header value.
    """
    parts: list[bytes] = []
    for name, value in (fields or {}).items():
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
            ).encode()
        )
    parts.append(
        (
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f'name="file"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + content
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
