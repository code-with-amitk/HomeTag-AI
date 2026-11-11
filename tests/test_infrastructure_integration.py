"""Integration tests requiring PostgreSQL with pgvector and Redis."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.main import create_app

requires_test_services = pytest.mark.skipif(
    get_settings().environment != "test",
    reason="requires PostgreSQL and Redis configured for the test environment",
)


@requires_test_services
def test_postgres_pgvector_and_redis_are_ready() -> None:
    """Verify migrations and dependency connectivity against configured test services."""
    app = create_app(get_settings())

    with TestClient(app) as client:
        response = client.get("/health/ready")
        with app.state.engine.connect() as connection:
            extension = connection.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            ).scalar_one_or_none()

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "components": {"database": "ok", "redis": "ok"},
    }
    assert extension == "vector"
