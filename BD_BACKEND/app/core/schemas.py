"""Pydantic schemas for the auth and user APIs: requests, user responses and the error body.

Needed so the API boundary validates input strictly and never serializes the User ORM
object (which holds the password hash); the /auth and /users routes use the request and
user schemas, and the OpenAPI schema uses ErrorResponse to document the 401 and 403 bodies.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.models import UserRole
from app.core.services import EMAIL_MAX_LENGTH

# Matches the practical upper bound on what the Argon2 hasher should be asked to process.
PASSWORD_MAX_LENGTH = 1024
# Shortest initial password an admin may set for a new user. Login does not enforce it, so
# older or seeded accounts with shorter passwords can still sign in.
PASSWORD_MIN_LENGTH = 12


class LoginRequest(BaseModel):
    """Body of POST /auth/login. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    email: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=EMAIL_MAX_LENGTH)
    ]
    # Deliberately not stripped or altered: leading/trailing spaces are part of a password.
    password: Annotated[str, Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)]

    @field_validator("email")
    @classmethod
    def _email_has_at_sign(cls, value: str) -> str:
        """Require an "@"; full address validation is not needed to look a user up.

        Raises:
            ValueError: If the email contains no "@".
        """
        if "@" not in value:
            raise ValueError("email must contain '@'")
        return value


class UserResponse(BaseModel):
    """The signed-in user as returned by the API: no password hash, no timestamps."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    email: str
    role: UserRole


class UserDetailResponse(UserResponse):
    """A user as shown on the admin user list and "my profile": adds status and timestamps.

    Never includes the password hash.
    """

    is_active: bool
    created_at: datetime
    updated_at: datetime


class CreateUserRequest(BaseModel):
    """Body of POST /users: the new user's email, role and the admin-set initial password."""

    model_config = ConfigDict(extra="forbid")

    email: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=EMAIL_MAX_LENGTH)
    ]
    role: UserRole
    # Not stripped: spaces are part of a password. Hashed with Argon2id before storage.
    password: Annotated[str, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)]

    @field_validator("email")
    @classmethod
    def _email_has_at_sign(cls, value: str) -> str:
        """Require an "@"; see LoginRequest for why full validation is not attempted.

        Raises:
            ValueError: If the email contains no "@".
        """
        if "@" not in value:
            raise ValueError("email must contain '@'")
        return value


class ChangeRoleRequest(BaseModel):
    """Body of PATCH /users/{id}: the user's new role."""

    model_config = ConfigDict(extra="forbid")

    role: UserRole


class ValidationErrorItem(BaseModel):
    """One rejected field in a 422: where it was, why, and the error type; never the value."""

    model_config = ConfigDict(extra="forbid")

    type: str
    loc: list[str | int]
    msg: str


class ValidationErrorResponse(BaseModel):
    """Body of a 422, exactly as core.errors.validation_error_handler returns it."""

    model_config = ConfigDict(extra="forbid")

    detail: list[ValidationErrorItem]


class ErrorResponse(BaseModel):
    """Body of a 401 or 403: one fixed message, nothing about the user, owner or capability."""

    model_config = ConfigDict(extra="forbid")

    detail: str
