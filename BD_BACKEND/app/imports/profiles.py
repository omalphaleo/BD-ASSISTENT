"""Admin service for source profiles: list, create, edit, deactivate, trim saved headers.

Needed so admins (MANAGE_SOURCE_PROFILES, D-049, D-104) can maintain the saved descriptions of
recurring source files that uploaders pick in the import wizard. Profiles are never deleted
(past imports keep pointing at them); an inactive profile just leaves the uploader's picker.
Saved header mappings are added only by "save as default" in imports.mapping and can be
removed here. Route handlers stay thin: every rule lives in this module.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.services import AuditAction, record
from app.core.models import User
from app.imports.errors import MappingRejectedError, ProfileErrorKind, ProfileRejectedError
from app.imports.layouts import normalize_header
from app.imports.mapping import PROFILE_AUDIT_OBJECT_TYPE, MappingDefaults, load_defaults
from app.imports.models import ImportFile, ImportStatus, SourceProfile

# Imports that still use their profile's mapping: deactivating the profile does not stop them,
# but the admin is told (they will no longer find it in the picker).
IN_PROGRESS_STATUSES = (ImportStatus.UPLOADED, ImportStatus.MAPPING, ImportStatus.PROCESSING)

NOT_FOUND_MESSAGE = "That source profile does not exist."
DUPLICATE_NAME_MESSAGE = "A source profile with this name already exists."
INVALID_DEFAULTS_MESSAGE = (
    "The saved mapping of this source profile is invalid and cannot be edited."
)
UNKNOWN_COLUMN_MESSAGE = "One or more headers are not in this profile's saved mapping."


@dataclass(frozen=True, slots=True)
class ProfileUpdateResult:
    """The profile after an edit, plus non-blocking warnings for the admin.

    Attributes:
        profile: The updated profile.
        warnings: Human-readable notes; empty when there is nothing to flag.
    """

    profile: SourceProfile
    warnings: list[str] = field(default_factory=list)


def saved_columns(profile: SourceProfile) -> dict[str, str] | None:
    """The profile's saved header -> field map, or None when the stored JSON is invalid."""
    try:
        return dict(load_defaults(profile).columns)
    except MappingRejectedError:
        return None


def list_profiles(db: Session) -> list[SourceProfile]:
    """Every profile, active and inactive, by name (the admin list)."""
    return list(db.execute(select(SourceProfile).order_by(SourceProfile.name)).scalars())


def get_profile(db: Session, profile_id: uuid.UUID) -> SourceProfile:
    """Return one profile.

    Raises:
        ProfileRejectedError: NOT_FOUND if there is no such profile.
    """
    profile = db.get(SourceProfile, profile_id)
    if profile is None:
        raise ProfileRejectedError(ProfileErrorKind.NOT_FOUND, NOT_FOUND_MESSAGE)
    return profile


def _name_taken(db: Session, name: str, *, except_id: uuid.UUID | None = None) -> bool:
    """True if another profile has this name, ignoring upper/lower case.

    The database constraint is case-sensitive, so "Apollo" and "apollo" would both pass it;
    comparing lowercase here keeps names unambiguous for the picker without a migration.
    """
    query = select(SourceProfile.id).where(func.lower(SourceProfile.name) == name.lower())
    if except_id is not None:
        query = query.where(SourceProfile.id != except_id)
    return db.execute(query.limit(1)).first() is not None


def _commit_or_duplicate(db: Session) -> None:
    """Commit; a concurrent insert of the same exact name becomes the same duplicate error."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ProfileRejectedError(ProfileErrorKind.DUPLICATE_NAME, DUPLICATE_NAME_MESSAGE) from exc


def create_profile(
    db: Session, actor: User, *, name: str, layout: str, ip_address: str | None = None
) -> SourceProfile:
    """Create an active profile with empty saved mapping defaults; commits.

    Raises:
        ProfileRejectedError: DUPLICATE_NAME if the name is taken (case-insensitive).
    """
    if _name_taken(db, name):
        raise ProfileRejectedError(ProfileErrorKind.DUPLICATE_NAME, DUPLICATE_NAME_MESSAGE)
    profile = SourceProfile(
        name=name,
        layout=layout,
        mapping_defaults=MappingDefaults().model_dump(mode="json"),
        is_active=True,
        created_by=actor.id,
    )
    db.add(profile)
    db.flush()
    record(
        db,
        action=AuditAction.SOURCE_PROFILE_CREATED,
        actor_user_id=actor.id,
        object_type=PROFILE_AUDIT_OBJECT_TYPE,
        object_id=str(profile.id),
        summary={"name": name, "layout": layout},
        ip_address=ip_address,
    )
    _commit_or_duplicate(db)
    return profile


def _count_in_progress_imports(db: Session, profile_id: uuid.UUID) -> int:
    """Imports that use this profile and are not finished yet."""
    return db.execute(
        select(func.count())
        .select_from(ImportFile)
        .where(ImportFile.source_profile_id == profile_id)
        .where(ImportFile.status.in_(IN_PROGRESS_STATUSES))
    ).scalar_one()


def update_profile(
    db: Session,
    actor: User,
    profile_id: uuid.UUID,
    *,
    name: str | None = None,
    layout: str | None = None,
    is_active: bool | None = None,
    ip_address: str | None = None,
) -> ProfileUpdateResult:
    """Rename, relabel, activate or deactivate a profile (None leaves a field alone); commits.

    Deactivating a profile that unfinished imports still use is allowed but returns a warning.
    The audit summary lists the changed fields with old and new values.

    Raises:
        ProfileRejectedError: NOT_FOUND; DUPLICATE_NAME if the new name is taken by another
            profile (case-insensitive).
    """
    profile = get_profile(db, profile_id)
    if name is not None and _name_taken(db, name, except_id=profile.id):
        raise ProfileRejectedError(ProfileErrorKind.DUPLICATE_NAME, DUPLICATE_NAME_MESSAGE)

    changes: dict[str, dict[str, object]] = {}
    for attribute, new_value in (("name", name), ("layout", layout), ("is_active", is_active)):
        old_value = getattr(profile, attribute)
        if new_value is not None and new_value != old_value:
            changes[attribute] = {"old": old_value, "new": new_value}
            setattr(profile, attribute, new_value)

    warnings: list[str] = []
    if "is_active" in changes and is_active is False:
        in_progress = _count_in_progress_imports(db, profile.id)
        if in_progress:
            warnings.append(
                f"{in_progress} import(s) still in progress use this profile. They keep "
                "working, but the profile no longer appears in the picker."
            )
    if changes:
        record(
            db,
            action=AuditAction.SOURCE_PROFILE_UPDATED,
            actor_user_id=actor.id,
            object_type=PROFILE_AUDIT_OBJECT_TYPE,
            object_id=str(profile.id),
            summary={"step": "profile_edited", "changes": changes},
            ip_address=ip_address,
        )
    _commit_or_duplicate(db)
    return ProfileUpdateResult(profile=profile, warnings=warnings)


def remove_default_columns(
    db: Session,
    actor: User,
    profile_id: uuid.UUID,
    headers: list[str],
    *,
    ip_address: str | None = None,
) -> SourceProfile:
    """Remove saved header mappings from a profile's defaults; commits.

    Headers are matched by normalized text, like when they were saved (D-040). The profile's
    formats are kept. Nothing is changed if any header is unknown.

    Raises:
        ProfileRejectedError: NOT_FOUND; INVALID_DEFAULTS if the stored mapping is invalid;
            UNKNOWN_COLUMN if a header is not in the saved mapping.
    """
    profile = get_profile(db, profile_id)
    try:
        defaults = load_defaults(profile)
    except MappingRejectedError as exc:
        raise ProfileRejectedError(
            ProfileErrorKind.INVALID_DEFAULTS, INVALID_DEFAULTS_MESSAGE
        ) from exc

    to_remove = {normalize_header(header) for header in headers}
    if not to_remove <= defaults.columns.keys():
        raise ProfileRejectedError(ProfileErrorKind.UNKNOWN_COLUMN, UNKNOWN_COLUMN_MESSAGE)

    remaining = {k: v for k, v in defaults.columns.items() if k not in to_remove}
    # A new dict is assigned (not mutated in place) so SQLAlchemy sees the JSONB change.
    profile.mapping_defaults = MappingDefaults(
        columns=remaining, formats=dict(defaults.formats)
    ).model_dump(mode="json")
    record(
        db,
        action=AuditAction.SOURCE_PROFILE_UPDATED,
        actor_user_id=actor.id,
        object_type=PROFILE_AUDIT_OBJECT_TYPE,
        object_id=str(profile.id),
        summary={"step": "mapping_defaults_removed", "columns_removed": len(to_remove)},
        ip_address=ip_address,
    )
    db.commit()
    return profile
