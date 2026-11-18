"""Tests for the /health route: healthy database and unreachable database.

Needed because probes (Docker, operators) rely on /health returning 200 when the database
works and a clean 503 body when it does not. Database access is swapped in through
FastAPI dependency overrides.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import get_session
from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide a TestClient and clear dependency overrides afterwards.

    Overrides are set on the global app object, so clearing them stops one test's fake
    database from leaking into the next.
    """
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_ok(client: TestClient, test_database_url: str) -> None:
    """Reachable database: /health returns 200 with status ok and database ok."""
    engine = create_engine(test_database_url)

    # Stands in for get_session so the route uses the throwaway test database, not DATABASE_URL.
    def override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    response = client.get("/health")
    engine.dispose()
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_returns_503_when_database_unreachable(client: TestClient) -> None:
    """Unreachable database: /health returns 503 with status degraded, database unavailable."""
    # Port 1 on localhost refuses connections; the 1-second timeout keeps the test fast.
    engine = create_engine(
        "postgresql+psycopg://nobody:nopass@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )

    # Stands in for get_session so the route is forced onto the unreachable database.
    def override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    response = client.get("/health")
    engine.dispose()
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}
