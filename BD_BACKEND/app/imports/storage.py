"""File storage for uploaded import files: a small protocol and a local-directory version.

Needed so the API (which receives uploads) and the worker (which later reads them) share one
way to keep file bytes outside PostgreSQL, and so the backing store can be replaced (for
example by object storage) without touching the upload or pipeline code. Only the key is kept
in the database (import_files.storage_key); callers never build paths themselves.
"""

import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO, Protocol

from app.config import get_settings
from app.imports.errors import StorageError

# Keys are server-generated: 32 hex characters plus a known extension. Validating on every
# call means a bad key can never escape the storage directory, whatever the caller passes.
# Always matched with fullmatch(): "$" would also accept a trailing newline.
STORAGE_KEY_PATTERN = re.compile(r"[0-9a-f]{32}\.(csv|xlsx)")
COPY_CHUNK_BYTES = 1024 * 1024


class FileStorage(Protocol):
    """What the import code needs from a file store."""

    def save(self, key: str, source: BinaryIO) -> int:
        """Store the bytes of source under key; return the number of bytes written."""
        ...

    def open(self, key: str) -> BinaryIO:
        """Open the stored object for binary reading."""
        ...

    def delete(self, key: str) -> None:
        """Remove the stored object; removing a missing object is not an error."""
        ...


def new_storage_key(extension: str) -> str:
    """Return a fresh random storage key such as '3f2a...e9.csv'.

    Args:
        extension: 'csv' or 'xlsx' (no dot).

    Raises:
        ValueError: If the extension is not one the storage accepts.
    """
    key = f"{uuid.uuid4().hex}.{extension}"
    if not STORAGE_KEY_PATTERN.fullmatch(key):
        raise ValueError(f"unsupported storage extension: {extension!r}")
    return key


class LocalDiskStorage:
    """Stores objects as files in one directory (a volume shared by the api and the worker)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path_for(self, key: str) -> Path:
        """Map a key to its file path inside the root.

        Raises:
            StorageError: If the key does not have the server-generated shape.
        """
        if not STORAGE_KEY_PATTERN.fullmatch(key):
            raise StorageError("invalid storage key")
        return self._root / key

    def save(self, key: str, source: BinaryIO) -> int:
        """Copy source to <root>/<key> atomically and return the size in bytes.

        The bytes go to a temporary file in the same directory and are then renamed, so a
        reader never sees a half-written file and a crash leaves no object under the key.

        Raises:
            StorageError: On an invalid key or any filesystem failure.
        """
        target = self._path_for(key)
        temp_name: str | None = None
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self._root, prefix=".tmp-", delete=False) as out:
                temp_name = out.name
                written = 0
                while chunk := source.read(COPY_CHUNK_BYTES):
                    out.write(chunk)
                    written += len(chunk)
            os.replace(temp_name, target)
            temp_name = None
            return written
        except OSError as exc:
            raise StorageError("could not save the file") from exc
        finally:
            if temp_name is not None:
                Path(temp_name).unlink(missing_ok=True)

    def open(self, key: str) -> BinaryIO:
        """Open <root>/<key> for reading.

        Raises:
            StorageError: On an invalid key or if the object is missing or unreadable.
        """
        try:
            return self._path_for(key).open("rb")
        except OSError as exc:
            raise StorageError("could not read the file") from exc

    def delete(self, key: str) -> None:
        """Delete <root>/<key> if it exists.

        Raises:
            StorageError: On an invalid key or a filesystem failure other than "missing".
        """
        try:
            self._path_for(key).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError("could not delete the file") from exc


def get_file_storage() -> FileStorage:
    """FastAPI dependency: the storage configured by UPLOAD_DIR (tests override it)."""
    return LocalDiskStorage(Path(get_settings().upload_dir))
