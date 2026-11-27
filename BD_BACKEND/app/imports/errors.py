"""Errors raised while receiving and reading an uploaded import file.

Needed so the parsers, the storage service and the upload service can reject a file with one
exception type that the API turns into a clear 4xx response. Messages are fixed text: they
never contain file contents, file names from the user or server paths.
"""

import enum


class UploadErrorKind(enum.StrEnum):
    """Why an upload was refused; each kind maps to one HTTP status in imports.api."""

    UNSUPPORTED_TYPE = "unsupported_type"
    TOO_LARGE = "too_large"
    TOO_MANY_ROWS = "too_many_rows"
    EMPTY_FILE = "empty_file"
    MALFORMED_FILE = "malformed_file"
    UNSAFE_ARCHIVE = "unsafe_archive"
    AMBIGUOUS_CSV = "ambiguous_csv"
    BAD_WORKSHEET = "bad_worksheet"
    NOT_EDITABLE = "not_editable"


class UploadRejectedError(Exception):
    """An uploaded file was refused for a reason the user can act on.

    Attributes:
        kind: The category of the refusal.
        message: A fixed, client-safe explanation (no file contents or paths).
    """

    def __init__(self, kind: UploadErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class MappingErrorKind(enum.StrEnum):
    """Why a mapping step was refused; each kind maps to one HTTP status in imports.mapping_api."""

    NOT_EDITABLE = "not_editable"
    WORKSHEET_REQUIRED = "worksheet_required"
    UNKNOWN_PROFILE = "unknown_profile"
    INVALID_PROFILE = "invalid_profile"
    INVALID_MAPPING = "invalid_mapping"
    MAPPING_NOT_SAVED = "mapping_not_saved"
    FILE_NOT_READABLE = "file_not_readable"


class MappingRejectedError(Exception):
    """A mapping, profile or preview request was refused for a reason the user can act on.

    Attributes:
        kind: The category of the refusal.
        message: A fixed, client-safe explanation (no file contents or paths).
    """

    def __init__(self, kind: MappingErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class StartErrorKind(enum.StrEnum):
    """Why "start import" was refused; each kind maps to HTTP 409 in imports.api."""

    NOT_STARTABLE = "not_startable"
    ALREADY_PROCESSING = "already_processing"
    MAPPING_INCOMPLETE = "mapping_incomplete"


class StartRejectedError(Exception):
    """An import could not be started for a reason the user can act on.

    Attributes:
        kind: The category of the refusal.
        message: A fixed, client-safe explanation (no file contents or paths).
    """

    def __init__(self, kind: StartErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class AssignErrorKind(enum.StrEnum):
    """Why an owner assignment was refused; mapped to an HTTP status in imports.assignment_api."""

    NOT_ASSIGNABLE_YET = "not_assignable_yet"  # 409: the import has not completed
    USER_NOT_ASSIGNABLE = "user_not_assignable"  # 422: unknown or inactive target user


class AssignRejectedError(Exception):
    """An owner assignment was refused for a reason the manager can act on.

    Attributes:
        kind: The category of the refusal.
        message: A fixed, client-safe explanation (no lead data).
    """

    def __init__(self, kind: AssignErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class ReportErrorKind(enum.StrEnum):
    """Why a report or download was refused; mapped to HTTP 409 in imports.reports_api."""

    NOT_FINISHED = "not_finished"  # the import is still being processed or was never started


class ReportRejectedError(Exception):
    """A report or download was asked for before the import finished (D-050, D-111).

    Attributes:
        kind: The category of the refusal.
        message: A fixed, client-safe explanation (no lead data).
    """

    def __init__(self, kind: ReportErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class ProfileErrorKind(enum.StrEnum):
    """Why a source profile admin request was refused; mapped to HTTP in imports.profiles_api."""

    NOT_FOUND = "not_found"  # 404
    DUPLICATE_NAME = "duplicate_name"  # 409: another profile already has this name
    INVALID_DEFAULTS = "invalid_defaults"  # 409: the saved mapping is broken, fix it first
    UNKNOWN_COLUMN = "unknown_column"  # 422: a header to remove is not in the saved mapping


class ProfileRejectedError(Exception):
    """A source profile admin request was refused for a reason the admin can act on (D-049).

    Attributes:
        kind: The category of the refusal.
        message: A fixed, client-safe explanation.
    """

    def __init__(self, kind: ProfileErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class ImportNotFoundError(Exception):
    """The import does not exist, or the caller may not see it.

    Both cases look the same on purpose, so a 404 never reveals that someone else's import
    exists.
    """


class StorageError(Exception):
    """The file storage could not save, read or delete an object (an internal failure).

    Not shown to users: the API reports a generic 500 and the details stay in the server log.
    """
