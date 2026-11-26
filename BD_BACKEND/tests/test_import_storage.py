"""Tests for the import file storage (LocalDiskStorage and the storage key rules).

Needed because the stored bytes are shared by the api and the worker, and a bad key or a
half-written file would either leak outside the upload directory or corrupt an import. No
database is used; each test works in pytest's temporary directory.
"""

import io
import re
from pathlib import Path

import pytest

from app.imports.errors import StorageError
from app.imports.storage import STORAGE_KEY_PATTERN, LocalDiskStorage, new_storage_key


def test_new_storage_key_has_the_server_generated_shape() -> None:
    """A fresh key is 32 hex characters plus the extension and is different every time."""
    first, second = new_storage_key("csv"), new_storage_key("xlsx")
    assert STORAGE_KEY_PATTERN.fullmatch(first) and first.endswith(".csv")
    assert STORAGE_KEY_PATTERN.fullmatch(second) and second.endswith(".xlsx")
    assert first != second


def test_new_storage_key_rejects_an_unknown_extension() -> None:
    """Only csv and xlsx keys can be created."""
    with pytest.raises(ValueError):
        new_storage_key("exe")


def test_save_open_and_delete_round_trip(tmp_path: Path) -> None:
    """Saved bytes read back unchanged, the size is returned, and delete removes the object."""
    storage = LocalDiskStorage(tmp_path / "uploads")  # directory does not exist yet
    key = new_storage_key("csv")

    written = storage.save(key, io.BytesIO(b"a,b\r\n1,2\r\n"))

    assert written == 10
    with storage.open(key) as stored:
        assert stored.read() == b"a,b\r\n1,2\r\n"
    storage.delete(key)
    with pytest.raises(StorageError):
        storage.open(key)


def test_delete_of_a_missing_object_is_not_an_error(tmp_path: Path) -> None:
    """Deleting twice is safe, so cleanup code can run without checking first."""
    storage = LocalDiskStorage(tmp_path)
    key = new_storage_key("csv")
    storage.delete(key)
    storage.delete(key)


def test_save_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    """After a save only the final object exists in the directory (rename, no leftovers)."""
    storage = LocalDiskStorage(tmp_path)
    key = new_storage_key("xlsx")
    storage.save(key, io.BytesIO(b"x" * 100))
    assert [p.name for p in tmp_path.iterdir()] == [key]


@pytest.mark.parametrize(
    "bad_key",
    [
        "../outside.csv",
        "/etc/passwd",
        "name.csv",
        "a" * 32 + ".exe",
        "a" * 32 + ".csv/..",
        "a" * 32 + ".csv\n",  # a trailing newline must not slip through
        "",
    ],
)
def test_invalid_keys_are_refused_by_every_operation(tmp_path: Path, bad_key: str) -> None:
    """A key that is not server-generated cannot be saved, opened or deleted (no traversal)."""
    storage = LocalDiskStorage(tmp_path)
    with pytest.raises(StorageError):
        storage.save(bad_key, io.BytesIO(b"x"))
    with pytest.raises(StorageError):
        storage.open(bad_key)
    with pytest.raises(StorageError):
        storage.delete(bad_key)
    assert not re.search(r"outside|passwd", " ".join(p.name for p in tmp_path.iterdir()))
