import pytest
from pydantic import ValidationError

from app.config import Settings


def test_missing_database_url_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_psycopg_conninfo_strips_driver_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    assert Settings(_env_file=None).psycopg_conninfo == "postgresql://u:p@h:5432/d"
