"""Safety checks on an XLSX file's ZIP container, run before openpyxl opens it.

Needed because an XLSX is a ZIP archive and a small upload can expand into gigabytes (a
decompression bomb) or hide an encrypted or broken container. check_xlsx_archive() reads only
the archive's table of contents and never extracts anything; the upload service and the
worksheet selection both call it before the file reaches openpyxl.
"""

import zipfile
from dataclasses import dataclass
from typing import BinaryIO

from app.imports.errors import UploadErrorKind, UploadRejectedError

# Members smaller than this are exempt from the ratio test: tiny XML files can compress
# extremely well without being dangerous, and would otherwise cause false rejections.
MIN_RATIO_CHECK_BYTES = 64 * 1024
# Every real XLSX has a workbook part; a ZIP without it is some other kind of archive.
REQUIRED_MEMBER = "xl/workbook.xml"
# Bit 0 of the general-purpose flags marks a member as password-encrypted.
ENCRYPTED_FLAG_BIT = 0x1

NOT_XLSX_MESSAGE = "The file is not a valid, unprotected XLSX workbook."
UNSAFE_MESSAGE = "The XLSX file is too large when unpacked or has an unsafe structure."


@dataclass(frozen=True, slots=True)
class ZipLimits:
    """Upper bounds for an XLSX archive (configured in app.config)."""

    max_entries: int
    max_member_bytes: int
    max_total_bytes: int
    max_compression_ratio: int


def check_xlsx_archive(source: BinaryIO, limits: ZipLimits) -> None:
    """Validate the archive's entry count, sizes, ratio and shape without extracting it.

    The sizes come from the archive's directory. A forged small size does not help an
    attacker: Python's zipfile stops reading a member at its declared size.

    Args:
        source: Seekable binary file positioned anywhere; its position is reset to the start.
        limits: The configured bounds.

    Raises:
        UploadRejectedError: MALFORMED_FILE if it is not a readable ZIP, is password-protected
            (Office encryption is not a ZIP at all) or lacks xl/workbook.xml; UNSAFE_ARCHIVE
            if any bound is exceeded or a member is encrypted.
    """
    source.seek(0)
    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError) as exc:
        raise UploadRejectedError(UploadErrorKind.MALFORMED_FILE, NOT_XLSX_MESSAGE) from exc
    finally:
        source.seek(0)

    if REQUIRED_MEMBER not in {member.filename for member in members}:
        raise UploadRejectedError(UploadErrorKind.MALFORMED_FILE, NOT_XLSX_MESSAGE)
    if len(members) > limits.max_entries:
        raise UploadRejectedError(UploadErrorKind.UNSAFE_ARCHIVE, UNSAFE_MESSAGE)

    total_bytes = 0
    for member in members:
        if member.flag_bits & ENCRYPTED_FLAG_BIT:
            raise UploadRejectedError(UploadErrorKind.UNSAFE_ARCHIVE, UNSAFE_MESSAGE)
        if member.file_size > limits.max_member_bytes:
            raise UploadRejectedError(UploadErrorKind.UNSAFE_ARCHIVE, UNSAFE_MESSAGE)
        total_bytes += member.file_size
        if (
            member.file_size >= MIN_RATIO_CHECK_BYTES
            and member.file_size > max(member.compress_size, 1) * limits.max_compression_ratio
        ):
            raise UploadRejectedError(UploadErrorKind.UNSAFE_ARCHIVE, UNSAFE_MESSAGE)
    if total_bytes > limits.max_total_bytes:
        raise UploadRejectedError(UploadErrorKind.UNSAFE_ARCHIVE, UNSAFE_MESSAGE)
