"""Read an upload request body in chunks, enforcing the size limit while it arrives.

Needed because FastAPI's normal file parameter buffers the whole body before the handler runs,
so a 2 GB upload would be accepted first and refused later. read_upload() counts bytes as they
stream in and stops at the limit, then hashes the received file. The HTTP layer (imports.api)
calls it; the upload service never sees HTTP.
"""

import hashlib
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import BinaryIO

from fastapi import Request
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.imports.errors import UploadErrorKind, UploadRejectedError

# Allowance on top of the file limit for multipart boundaries and the small form fields.
FORM_OVERHEAD_BYTES = 64 * 1024
MAX_FORM_FIELDS = 4
MAX_FORM_FILES = 1
FILE_FIELD = "file"
ALLOW_DUPLICATE_FIELD = "allow_duplicate"
TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
HASH_CHUNK_BYTES = 1024 * 1024

TOO_LARGE_MESSAGE = "The file is larger than the upload limit."
BAD_FORM_MESSAGE = "The upload must be a multipart form with one file field named 'file'."


@dataclass(slots=True)
class ReceivedUpload:
    """A fully received upload: the buffered file, its size, hash, name and form flag.

    The caller must call close() when finished, which releases the temporary file.
    """

    file: BinaryIO
    size_bytes: int
    sha256: str
    filename: str
    allow_duplicate: bool
    _upload: UploadFile

    async def close(self) -> None:
        """Release the temporary file buffer."""
        await self._upload.close()


def _too_large() -> UploadRejectedError:
    """The error for a body or file above the configured limit."""
    return UploadRejectedError(UploadErrorKind.TOO_LARGE, TOO_LARGE_MESSAGE)


async def _limited_stream(request: Request, limit: int) -> AsyncGenerator[bytes, None]:
    """Yield the request body chunk by chunk and raise as soon as it exceeds the limit."""
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            raise _too_large()
        yield chunk


def _sha256_of(file: BinaryIO) -> str:
    """Hash the whole file in chunks and rewind it."""
    digest = hashlib.sha256()
    file.seek(0)
    while chunk := file.read(HASH_CHUNK_BYTES):
        digest.update(chunk)
    file.seek(0)
    return digest.hexdigest()


async def read_upload(request: Request, max_file_bytes: int) -> ReceivedUpload:
    """Receive a multipart upload with a 'file' part and an optional 'allow_duplicate' field.

    Args:
        request: The incoming request (its body is consumed).
        max_file_bytes: The largest file accepted (D-110: 20 MB).

    Raises:
        UploadRejectedError: TOO_LARGE if the body or the file passes the limit (checked on the
            Content-Length header first, then again while streaming); MALFORMED_FILE if the
            body is not a multipart form with exactly one 'file' part.
    """
    body_limit = max_file_bytes + FORM_OVERHEAD_BYTES
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > body_limit:
        raise _too_large()

    parser = MultiPartParser(
        request.headers,
        _limited_stream(request, body_limit),
        max_files=MAX_FORM_FILES,
        max_fields=MAX_FORM_FIELDS,
    )
    try:
        form = await parser.parse()
    except MultiPartException as exc:
        raise UploadRejectedError(UploadErrorKind.MALFORMED_FILE, BAD_FORM_MESSAGE) from exc

    upload = form.get(FILE_FIELD)
    if not isinstance(upload, UploadFile):
        raise UploadRejectedError(UploadErrorKind.MALFORMED_FILE, BAD_FORM_MESSAGE)
    received = ReceivedUpload(
        file=upload.file,
        size_bytes=upload.size or 0,
        sha256="",
        filename=upload.filename or "",
        allow_duplicate=str(form.get(ALLOW_DUPLICATE_FIELD, "")).strip().lower() in TRUE_VALUES,
        _upload=upload,
    )
    if received.size_bytes > max_file_bytes:
        await received.close()
        raise _too_large()
    received.sha256 = _sha256_of(upload.file)
    return received
