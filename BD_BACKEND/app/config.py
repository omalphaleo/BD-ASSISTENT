"""Typed application settings read from environment variables (and a local .env file).

Needed so configuration never lives in code and a missing DATABASE_URL or an unsafe
production setting stops the process at startup; app.db, app.worker and the Alembic
environment all read their configuration through get_settings().
"""

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_ENV = "production"
DEFAULT_SESSION_LIFETIME_HOURS = 12
DEFAULT_SESSION_COOKIE_NAME = "bd_session"
DEFAULT_FRONTEND_ORIGIN = "http://localhost:3000"
ALLOWED_ORIGIN_SCHEMES = ("http", "https")
DEFAULT_LOGIN_MAX_FAILURES_PER_ACCOUNT = 5
DEFAULT_LOGIN_MAX_FAILURES_PER_IP = 20
DEFAULT_LOGIN_THROTTLE_WINDOW_MINUTES = 15

# Import upload limits (M2-A1). The 20 MB and 50,000-row limits are D-110; the ZIP limits are
# the values approved on 2026-11-26 and guard against decompression bombs in XLSX files.
BYTES_PER_MEGABYTE = 1024 * 1024
DEFAULT_UPLOAD_DIR = "/srv/uploads"
DEFAULT_UPLOAD_MAX_BYTES = 20 * BYTES_PER_MEGABYTE
DEFAULT_UPLOAD_MAX_ROWS = 50_000
DEFAULT_XLSX_MAX_ENTRIES = 1_000
DEFAULT_XLSX_MAX_MEMBER_BYTES = 100 * BYTES_PER_MEGABYTE
DEFAULT_XLSX_MAX_TOTAL_BYTES = 200 * BYTES_PER_MEGABYTE
DEFAULT_XLSX_MAX_COMPRESSION_RATIO = 100

# Import processing (M2-A3). Rows per transaction: small enough that a crash loses little work
# and progress moves often, large enough to keep commit overhead low (approved 2026-11-27).
DEFAULT_IMPORT_CHUNK_SIZE = 500
# Days after contact before a person may enter a new campaign (D-082: 90 days); passed to
# ingest_row through ImportContext. No settings screen exists yet, so it is an env value.
DEFAULT_COOLING_OFF_DAYS = 90

# AI calls (M3-A6, approved 2026-11-28). NL search is an interactive request, so waits stay short:
# 10 s per attempt and at most 2 retries (3 attempts) for timeouts, 429 and 5xx.
DEFAULT_AI_TIMEOUT_SECONDS = 10
DEFAULT_AI_MAX_RETRIES = 2


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

    # Login throttling (env: LOGIN_MAX_FAILURES_PER_ACCOUNT, LOGIN_MAX_FAILURES_PER_IP,
    # LOGIN_THROTTLE_WINDOW_MINUTES): failed logins allowed inside the rolling window.
    login_max_failures_per_account: int = Field(
        default=DEFAULT_LOGIN_MAX_FAILURES_PER_ACCOUNT, gt=0
    )
    login_max_failures_per_ip: int = Field(default=DEFAULT_LOGIN_MAX_FAILURES_PER_IP, gt=0)
    login_throttle_window_minutes: int = Field(default=DEFAULT_LOGIN_THROTTLE_WINDOW_MINUTES, gt=0)

    # Import uploads (env: UPLOAD_DIR, UPLOAD_MAX_BYTES, UPLOAD_MAX_ROWS, XLSX_MAX_ENTRIES,
    # XLSX_MAX_MEMBER_BYTES, XLSX_MAX_TOTAL_BYTES, XLSX_MAX_COMPRESSION_RATIO). The directory
    # must be the same persistent volume in the api and worker containers.
    upload_dir: str = Field(default=DEFAULT_UPLOAD_DIR, min_length=1)
    upload_max_bytes: int = Field(default=DEFAULT_UPLOAD_MAX_BYTES, gt=0)
    upload_max_rows: int = Field(default=DEFAULT_UPLOAD_MAX_ROWS, gt=0)
    xlsx_max_entries: int = Field(default=DEFAULT_XLSX_MAX_ENTRIES, gt=0)
    xlsx_max_member_bytes: int = Field(default=DEFAULT_XLSX_MAX_MEMBER_BYTES, gt=0)
    xlsx_max_total_bytes: int = Field(default=DEFAULT_XLSX_MAX_TOTAL_BYTES, gt=0)
    xlsx_max_compression_ratio: int = Field(default=DEFAULT_XLSX_MAX_COMPRESSION_RATIO, gt=0)

    # Import processing (env: IMPORT_CHUNK_SIZE, COOLING_OFF_DAYS).
    import_chunk_size: int = Field(default=DEFAULT_IMPORT_CHUNK_SIZE, gt=0)
    cooling_off_days: int = Field(default=DEFAULT_COOLING_OFF_DAYS, ge=0)

    # AI provider (env: GEMINI_API_KEY, AI_TIMEOUT_SECONDS, AI_MAX_RETRIES). The key is optional on
    # purpose: structured search must keep working without it, so a missing key means "AI
    # unavailable" at request time, not a startup failure (approved 2026-11-28). SecretStr keeps it
    # out of reprs and logs. Development uses a free-tier key on test data only (D-062).
    gemini_api_key: SecretStr | None = None
    ai_timeout_seconds: int = Field(default=DEFAULT_AI_TIMEOUT_SECONDS, gt=0)
    ai_max_retries: int = Field(default=DEFAULT_AI_MAX_RETRIES, ge=0)

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
