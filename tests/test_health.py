"""Tests for process health and dependency readiness endpoints."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

import app.main as main_module
from app.core.config import Settings
from app.main import create_app


class FakeConnection:
    """Minimal SQLAlchemy connection substitute for readiness tests."""

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: object) -> None:
        return None


class FakeEngine:
    """Minimal SQLAlchemy engine substitute for readiness tests."""

    def connect(self) -> FakeConnection:
        return FakeConnection()

    def dispose(self) -> None:
        return None


class FakeRedis:
    """Minimal Redis client substitute for readiness tests."""

    should_fail: bool = False

    def ping(self) -> bool:
        if self.should_fail:
            raise RedisError("simulated Redis outage")
        return True

    def close(self) -> None:
        return None


@pytest.fixture
def fake_dependencies(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeRedis]:
    """Replace network resources with deterministic in-process fakes."""
    redis_client = FakeRedis()
    monkeypatch.setattr(main_module, "create_engine", lambda *args, **kwargs: FakeEngine())
    monkeypatch.setattr(main_module.Redis, "from_url", lambda *args, **kwargs: redis_client)
    yield redis_client


def test_liveness_returns_ok_and_request_id(fake_dependencies: FakeRedis) -> None:
    """Liveness does not depend on database or cache availability."""
    app = create_app(Settings(environment="test"))
    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_readiness_reports_available_dependencies(fake_dependencies: FakeRedis) -> None:
    """Readiness is successful when PostgreSQL and Redis respond."""
    app = create_app(Settings(environment="test"))
    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "components": {"database": "ok", "redis": "ok"},
    }


def test_readiness_returns_service_unavailable_when_redis_fails(
    fake_dependencies: FakeRedis,
) -> None:
    """Readiness identifies an unavailable dependency without exposing its error."""
    fake_dependencies.should_fail = True
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "components": {"database": "ok", "redis": "unavailable"},
    }
    assert "simulated Redis outage" not in response.text


def test_openapi_and_interactive_documentation_are_available(
    fake_dependencies: FakeRedis,
) -> None:
    """FastAPI exposes schema, Swagger UI, and ReDoc."""
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        schema = client.get("/openapi.json")
        swagger = client.get("/docs")
        redoc = client.get("/redoc")

    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "HomeTag AI"
    assert "/health/live" in schema.json()["paths"]
    assert "/health/ready" in schema.json()["paths"]
    assert swagger.status_code == 200
    assert redoc.status_code == 200


def test_invalid_database_configuration_is_rejected() -> None:
    """Unsupported database URLs fail during settings validation."""
    with pytest.raises(ValueError, match="database_url"):
        Settings(database_url="sqlite:///unsupported.db")
