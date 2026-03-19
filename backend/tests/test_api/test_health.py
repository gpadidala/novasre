"""
Tests for health check endpoints.
"""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_liveness_always_ok(client):
    """GET /api/health always returns 200."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_readiness_with_healthy_deps(client):
    """GET /api/health/ready returns 200 when DB and Redis are up."""
    with (
        patch("app.api.v1.health.check_db_connection", new_callable=AsyncMock) as mock_db,
        patch("app.api.v1.health.check_redis_connection", new_callable=AsyncMock) as mock_redis,
    ):
        mock_db.return_value = True
        mock_redis.return_value = True

        response = await client.get("/api/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["db"] == "ok"
        assert data["redis"] == "ok"


@pytest.mark.asyncio
async def test_readiness_with_db_down(client):
    """GET /api/health/ready returns 503 when DB is unreachable."""
    with (
        patch("app.api.v1.health.check_db_connection", new_callable=AsyncMock) as mock_db,
        patch("app.api.v1.health.check_redis_connection", new_callable=AsyncMock) as mock_redis,
    ):
        mock_db.return_value = False
        mock_redis.return_value = True

        response = await client.get("/api/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["db"] == "error"
        assert data["redis"] == "ok"


@pytest.mark.asyncio
async def test_readiness_with_redis_down(client):
    """GET /api/health/ready returns 503 when Redis is unreachable."""
    with (
        patch("app.api.v1.health.check_db_connection", new_callable=AsyncMock) as mock_db,
        patch("app.api.v1.health.check_redis_connection", new_callable=AsyncMock) as mock_redis,
    ):
        mock_db.return_value = True
        mock_redis.return_value = False

        response = await client.get("/api/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["redis"] == "error"


@pytest.mark.asyncio
async def test_root_endpoint(client):
    """GET / returns service info."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "NovaSRE"
    assert "docs" in data
    assert "health" in data
