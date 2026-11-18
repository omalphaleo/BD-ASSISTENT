"""Typed application settings read from environment variables (and a local .env file).

Needed so configuration never lives in code and a missing DATABASE_URL or an unsafe
production setting stops the process at startup; app.db, app.worker and the Alembic
environment all read their configuration through get_settings().
"""

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_ENV = "production"
DEFAULT_SESSION_LIFETIME_HOURS = 12
DEFAULT_SESSION_COOKIE_NAME = "bd_session"
DEFAULT_FRONTEND_ORIGIN = "http://localhost:3000"
ALLOWED_ORIGIN_SCHEMES = ("http", "https")


class Settings(BaseSettings):
    """All runtime settings; field names map to upper-case environment variables.

    Raises:
        pydantic.ValidationError: On construction, if DATABASE_URL is missing or any
            value fails validation (including the production rules below).
    """

    # SQLAlchemy URL form: postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME
    database_url: str = Field(min_length=1)
    app_env: str = "development"

    # Session and cookie settings (env: SESSION_LIFETIME_HOURS, SESSION_COOKIE_NAME,
    # SESSION_COOKIE_SECURE, FRONTEND_ORIGIN). SameSite is fixed to Lax in the cookie code.
    session_lifetime_hours: int = Field(default=DEFAULT_SESSION_LIFETIME_HOURS, gt=0)
    session_cookie_name: str = Field(default=DEFAULT_SESSION_COOKIE_NAME, min_length=1)
    # Secure cookies are on by default; only local plain-HTTP development turns them off.
    session_cookie_secure: bool = True
    # Exact browser origin of the frontend: scheme + host (+ optional port), no path.
    frontend_origin: str = DEFAULT_FRONTEND_ORIGIN

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _validate_session_and_origin(self) -> "Settings":
        """Check frontend_origin shape and enforce HTTPS-only cookies/origin in production.

        Raises:
            ValueError: If frontend_origin is not a bare http(s) origin, or if production
                runs with insecure cookies or a non-https frontend origin.
        """
        parts = urlsplit(self.frontend_origin)
        if parts.scheme not in ALLOWED_ORIGIN_SCHEMES or not parts.hostname:
            raise ValueError(
                "FRONTEND_ORIGIN must start with http:// or https:// and include a host, "
                f"got {self.frontend_origin!r}"
            )
        # Credentials (user:pass@host) never belong in an origin and could leak into logs.
        if parts.username is not None or parts.password is not None:
            raise ValueError("FRONTEND_ORIGIN must not contain credentials (user@host)")
        # A trailing slash counts as a path: an origin must match the browser's Origin header.
        if parts.path or parts.query or parts.fragment:
            raise ValueError(
                "FRONTEND_ORIGIN must be an origin only (no path, trailing slash, query or "
                f"fragment), got {self.frontend_origin!r}"
            )
        if self.app_env == PRODUCTION_ENV:
            if not self.session_cookie_secure:
                raise ValueError("SESSION_COOKIE_SECURE must be true when APP_ENV=production")
            if parts.scheme != "https":
                raise ValueError("FRONTEND_ORIGIN must use https when APP_ENV=production")
        return self

    @property
    def psycopg_conninfo(self) -> str:
        """Plain libpq URL (no SQLAlchemy driver suffix), used by Procrastinate."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings, built once and cached.

    Raises:
        pydantic.ValidationError: If required settings are missing or invalid.
    """
    return Settings()  # raises ValidationError if DATABASE_URL is missing
