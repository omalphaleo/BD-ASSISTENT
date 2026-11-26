"""Who may see or change an import file (object-level rules for the imports module).

Needed because the IMPORT_LEADS capability only says "may use imports"; it does not say whose
imports. Keeping the rule in these two functions means the endpoints and services all apply
the same decision, and a later team scope only has to change this file. The download
permission (DOWNLOAD_IMPORT_FILES) is separate and not decided here.
"""

from app.core.models import User, UserRole
from app.imports.models import ImportFile


def can_view_import(user: User, import_file: ImportFile) -> bool:
    """Reps see only their own imports; managers and admins see all (decision 2026-11-26).

    Users have no team link yet, so "managers within their scope" means every import.
    """
    if user.role in (UserRole.MANAGER, UserRole.ADMIN):
        return True
    return import_file.uploaded_by is not None and import_file.uploaded_by == user.id


def can_change_import(user: User, import_file: ImportFile) -> bool:
    """Only the user who uploaded the file may change it (choose its worksheet).

    Viewing is wider than changing: a manager can watch a rep's import but is not walking its
    wizard. If the uploader's account was deleted, nobody can change it.
    """
    return import_file.uploaded_by is not None and import_file.uploaded_by == user.id
