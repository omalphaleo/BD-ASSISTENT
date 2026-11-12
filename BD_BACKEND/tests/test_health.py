from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import get_session
from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_ok(client: TestClient, test_database_url: str) -> None:
    engine = create_engine(test_database_url)

    def override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    response = client.get("/health")
    engine.dispose()
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_returns_503_when_database_unreachable(client: TestClient) -> None:
    engine = create_engine(
        "postgresql+psycopg://nobody:nopass@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )

    def override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    response = client.get("/health")
    engine.dispose()
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}
