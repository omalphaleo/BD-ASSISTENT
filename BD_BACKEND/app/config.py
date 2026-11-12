"""Settings from environment variables. Missing required values fail fast."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # SQLAlchemy URL form: postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME
    database_url: str = Field(min_length=1)
    app_env: str = "development"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def psycopg_conninfo(self) -> str:
        """Plain libpq URL (no SQLAlchemy driver suffix), used by Procrastinate."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # raises ValidationError if DATABASE_URL is missing
