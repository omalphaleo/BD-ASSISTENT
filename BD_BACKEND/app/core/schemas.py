"""Pydantic schemas for the auth API: the login request and the user response.

Needed so the API boundary validates input strictly and never serializes the User ORM
object (which holds the password hash); the /auth routes use these two models only.
"""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.models import UserRole
from app.core.services import EMAIL_MAX_LENGTH

# Matches the practical upper bound on what the Argon2 hasher should be asked to process.
PASSWORD_MAX_LENGTH = 1024


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
