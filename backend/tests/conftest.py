"""
NovaSRE test configuration and fixtures.
Uses SQLite (in-memory) for fast tests without a live PostgreSQL instance.
Uses respx for mocking HTTP calls to Mimir, Loki, Tempo, Pyroscope, Faro.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.alert import Alert
from app.models.incident import Incident
from app.models.investigation import Investigation

# ---------------------------------------------------------------------------
# Async event loop
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


# ---------------------------------------------------------------------------
# In-memory SQLite database (fast, no external deps)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create a shared in-memory SQLite engine for the entire test session."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    # Import all models to register metadata
    import app.models.alert  # noqa
    import app.models.incident  # noqa
    import app.models.investigation  # noqa
    import app.models.knowledge  # noqa
    import app.models.service  # noqa

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh AsyncSession for each test, rolled back after."""
    session_factory = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# FastAPI test client with DB override
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP test client with DB dependency overridden."""
    from app.database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    # Mock Redis to avoid requiring a live Redis in tests
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.hset = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock(return_value=True)
    mock_redis.hgetall = AsyncMock(return_value={})
    mock_redis.publish = AsyncMock(return_value=1)

    with patch("app.dependencies._redis_pool", mock_redis):
        async with AsyncClient(app=app, base_url="http://testserver") as ac:
            yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sample model fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sample_incident(db_session: AsyncSession) -> Incident:
    """Create and persist a sample Incident."""
    incident = Incident(
        title="High error rate on checkout service",
        description="Error rate spiked to 12% after deployment at 14:30 UTC",
        severity="P2",
        status="open",
        affected_services=["checkout", "payment"],
        start_time=datetime.now(tz=timezone.utc),
    )
    db_session.add(incident)
    await db_session.flush()
    await db_session.refresh(incident)
    return incident


@pytest_asyncio.fixture
async def sample_alert(db_session: AsyncSession, sample_incident: Incident) -> Alert:
    """Create and persist a sample Alert linked to sample_incident."""
    alert = Alert(
        name="HighErrorRate",
        fingerprint=str(uuid.uuid4()).replace("-", "")[:32],
        labels={"app": "checkout", "severity": "critical", "alertname": "HighErrorRate"},
        annotations={
            "summary": "Error rate > 5% on checkout",
            "description": "Current error rate is 12.3%",
            "runbook_url": "https://runbooks.example.com/checkout-errors",
        },
        severity="critical",
        status="firing",
        source="alertmanager",
        fired_at=datetime.now(tz=timezone.utc),
        incident_id=sample_incident.id,
    )
    db_session.add(alert)
    await db_session.flush()
    await db_session.refresh(alert)
    return alert


@pytest_asyncio.fixture
async def sample_investigation(
    db_session: AsyncSession, sample_incident: Incident
) -> Investigation:
    """Create and persist a sample Investigation."""
    investigation = Investigation(
        incident_id=sample_incident.id,
        status="pending",
        created_by="test@example.com",
        tool_calls=[],
    )
    db_session.add(investigation)
    await db_session.flush()
    await db_session.refresh(investigation)
    return investigation


# ---------------------------------------------------------------------------
# Mock HTTP fixtures for observability backends
# ---------------------------------------------------------------------------

MIMIR_VECTOR_RESPONSE = {
    "status": "success",
    "data": {
        "resultType": "vector",
        "result": [
            {
                "metric": {"app": "checkout", "__name__": "http_requests_total"},
                "value": [1710000000, "0.05"],
            }
        ],
    },
}

MIMIR_RANGE_RESPONSE = {
    "status": "success",
    "data": {
        "resultType": "matrix",
        "result": [
            {
                "metric": {"app": "checkout"},
                "values": [
                    [1710000000, "0.02"],
                    [1710000060, "0.05"],
                    [1710000120, "0.12"],
                    [1710000180, "0.10"],
                ],
            }
        ],
    },
}

LOKI_RESPONSE = {
    "status": "success",
    "data": {
        "resultType": "streams",
        "result": [
            {
                "stream": {"app": "checkout", "level": "error"},
                "values": [
                    ["1710000000000000000", "ERROR: DB connection refused after 30s timeout"],
                    ["1710000005000000000", "ERROR: payment service unavailable: connection pool exhausted"],
                    ["1710000010000000000", "FATAL: checkout service panicking: nil pointer dereference"],
                ],
            }
        ],
    },
}

TEMPO_SEARCH_RESPONSE = {
    "traces": [
        {
            "traceID": "abc123def456",
            "rootServiceName": "checkout",
            "rootTraceName": "POST /checkout",
            "startTimeUnixNano": "1710000000000000000",
            "durationMs": 8234,
        }
    ]
}

PYROSCOPE_RESPONSE = {
    "flamebearer": {
        "names": ["total", "main.processOrder", "db.query", "net.dial"],
        "levels": [[0, 100, 0, 0], [0, 100, 0, 1], [0, 60, 0, 2], [0, 40, 0, 3]],
        "numTicks": 100,
        "maxSelf": 40,
    }
}


@pytest.fixture
def mock_mimir():
    """Mock Mimir HTTP endpoints with realistic metric responses."""
    with respx.mock(assert_all_mocked=False) as mock:
        mock.post(
            url__regex=r".*/prometheus/api/v1/query$"
        ).mock(return_value=httpx.Response(200, json=MIMIR_VECTOR_RESPONSE))

        mock.post(
            url__regex=r".*/prometheus/api/v1/query_range$"
        ).mock(return_value=httpx.Response(200, json=MIMIR_RANGE_RESPONSE))

        mock.get(
            url__regex=r".*/prometheus/api/v1/label/.*/values$"
        ).mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": ["checkout", "payment", "api-gateway"]}
            )
        )
        yield mock


@pytest.fixture
def mock_loki():
    """Mock Loki HTTP endpoints with realistic log responses."""
    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(
            url__regex=r".*/loki/api/v1/query_range$"
        ).mock(return_value=httpx.Response(200, json=LOKI_RESPONSE))
        yield mock


@pytest.fixture
def mock_tempo():
    """Mock Tempo HTTP endpoints with realistic trace responses."""
    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(
            url__regex=r".*/api/search$"
        ).mock(return_value=httpx.Response(200, json=TEMPO_SEARCH_RESPONSE))

        mock.get(
            url__regex=r".*/api/traces/.*$"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "traceID": "abc123def456",
                    "rootServiceName": "checkout",
                    "spans": [],
                },
            )
        )
        yield mock


@pytest.fixture
def mock_pyroscope():
    """Mock Pyroscope HTTP endpoints with realistic profile responses."""
    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(
            url__regex=r".*/pyroscope/render$"
        ).mock(return_value=httpx.Response(200, json=PYROSCOPE_RESPONSE))
        yield mock


@pytest.fixture
def mock_grafana():
    """Mock Grafana HTTP endpoints."""
    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(
            url__regex=r".*/api/alerting/alerts$"
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "uid": "test-alert-uid",
                        "name": "HighErrorRate",
                        "state": "alerting",
                        "labels": {"app": "checkout"},
                    }
                ],
            )
        )
        mock.get(
            url__regex=r".*/api/annotations$"
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "text": "Deployment: checkout v2.3.1",
                        "tags": ["deployment"],
                        "time": 1710000000000,
                    }
                ],
            )
        )
        yield mock


@pytest.fixture
def mock_all_backends(mock_mimir, mock_loki, mock_tempo, mock_pyroscope, mock_grafana):
    """Convenience fixture: mock all observability backends at once."""
    yield {
        "mimir": mock_mimir,
        "loki": mock_loki,
        "tempo": mock_tempo,
        "pyroscope": mock_pyroscope,
        "grafana": mock_grafana,
    }
