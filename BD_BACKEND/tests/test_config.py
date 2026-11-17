"""Tests for app.config.Settings: required values, derived URL and session/origin rules.

Needed so configuration problems (missing DATABASE_URL, malformed FRONTEND_ORIGIN, unsafe
production cookie settings) are proven to fail at startup instead of at run time.
Settings(_env_file=None) is used throughout so a developer's local .env cannot affect results.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_missing_database_url_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """No DATABASE_URL in the environment: Settings raises ValidationError."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_psycopg_conninfo_strips_driver_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    """A postgresql+psycopg:// URL becomes a plain postgresql:// URL for Procrastinate."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    assert Settings(_env_file=None).psycopg_conninfo == "postgresql://u:p@h:5432/d"


# --- Session / cookie / frontend-origin settings ---

# Every environment variable the session tests set; base_env clears them so a value exported
# in the developer's shell cannot change the expected defaults.
SESSION_ENV_VARS = (
    "APP_ENV",
    "SESSION_LIFETIME_HOURS",
    "SESSION_COOKIE_NAME",
    "SESSION_COOKIE_SECURE",
    "FRONTEND_ORIGIN",
)


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Set DATABASE_URL and clear all session-related variables for a clean environment."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    for name in SESSION_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_session_defaults(base_env: pytest.MonkeyPatch) -> None:
    """No overrides: lifetime 12h, cookie bd_session, secure on, localhost:3000 origin."""
    settings = Settings(_env_file=None)
    assert settings.session_lifetime_hours == 12
    assert settings.session_cookie_name == "bd_session"
    assert settings.session_cookie_secure is True
    assert settings.frontend_origin == "http://localhost:3000"


def test_session_settings_overridable_from_env(base_env: pytest.MonkeyPatch) -> None:
    """Each session setting is read from its environment variable."""
    base_env.setenv("SESSION_LIFETIME_HOURS", "4")
    base_env.setenv("SESSION_COOKIE_NAME", "custom_sid")
    base_env.setenv("SESSION_COOKIE_SECURE", "false")
    base_env.setenv("FRONTEND_ORIGIN", "https://bd.example.com")
    settings = Settings(_env_file=None)
    assert settings.session_lifetime_hours == 4
    assert settings.session_cookie_name == "custom_sid"
    assert settings.session_cookie_secure is False
    assert settings.frontend_origin == "https://bd.example.com"


@pytest.mark.parametrize("hours", ["0", "-1"])
def test_non_positive_session_lifetime_rejected(base_env: pytest.MonkeyPatch, hours: str) -> None:
    """Lifetime of 0 or a negative number is rejected."""
    base_env.setenv("SESSION_LIFETIME_HOURS", hours)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_empty_cookie_name_rejected(base_env: pytest.MonkeyPatch) -> None:
    """An empty SESSION_COOKIE_NAME is rejected."""
    base_env.setenv("SESSION_COOKIE_NAME", "")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000/",  # trailing slash counts as a path
        "https://bd.example.com/app",  # path
        "https://bd.example.com?x=1",  # query
        "bd.example.com",  # missing scheme
        "https://user@bd.example.com",  # credentials (username only)
        "https://user:pw@bd.example.com",  # credentials (username and password)
    ],
)
def test_malformed_frontend_origin_rejected(base_env: pytest.MonkeyPatch, origin: str) -> None:
    """Origins with a trailing slash, path, query, no scheme or credentials are rejected."""
    base_env.setenv("FRONTEND_ORIGIN", origin)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_frontend_origin_with_port_accepted(base_env: pytest.MonkeyPatch) -> None:
    """A valid origin with a port loads unchanged."""
    base_env.setenv("FRONTEND_ORIGIN", "http://localhost:8080")
    assert Settings(_env_file=None).frontend_origin == "http://localhost:8080"


def test_production_rejects_insecure_cookie(base_env: pytest.MonkeyPatch) -> None:
    """Production with SESSION_COOKIE_SECURE=false is rejected."""
    base_env.setenv("APP_ENV", "production")
    base_env.setenv("FRONTEND_ORIGIN", "https://bd.example.com")
    base_env.setenv("SESSION_COOKIE_SECURE", "false")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_production_rejects_http_origin(base_env: pytest.MonkeyPatch) -> None:
    """Production with an http:// frontend origin is rejected."""
    base_env.setenv("APP_ENV", "production")
    base_env.setenv("FRONTEND_ORIGIN", "http://bd.example.com")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_production_with_secure_cookie_and_https_origin_loads(base_env: pytest.MonkeyPatch) -> None:
    """Production with secure cookies and an https origin loads."""
    base_env.setenv("APP_ENV", "production")
    base_env.setenv("FRONTEND_ORIGIN", "https://bd.example.com")
    settings = Settings(_env_file=None)
    assert settings.session_cookie_secure is True


def test_development_allows_insecure_cookie_and_http_origin(base_env: pytest.MonkeyPatch) -> None:
    """Development with SESSION_COOKIE_SECURE=false and an http origin is accepted."""
    base_env.setenv("APP_ENV", "development")
    base_env.setenv("SESSION_COOKIE_SECURE", "false")
    base_env.setenv("FRONTEND_ORIGIN", "http://localhost:3000")
    assert Settings(_env_file=None).session_cookie_secure is False
