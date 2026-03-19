"""
Tests for the Incidents API.
"""
import uuid
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_list_incidents_empty(client):
    """GET /api/v1/incidents returns empty list when no incidents exist."""
    response = await client.get("/api/v1/incidents")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_create_incident(client):
    """POST /api/v1/incidents creates a new incident."""
    payload = {
        "title": "High error rate on checkout service",
        "description": "Error rate spiked to 12% after deployment",
        "severity": "P2",
        "status": "open",
        "affected_services": ["checkout", "payment"],
        "start_time": datetime.now(tz=timezone.utc).isoformat(),
    }
    response = await client.post("/api/v1/incidents", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == payload["title"]
    assert data["severity"] == "P2"
    assert data["status"] == "open"
    assert "id" in data
    assert uuid.UUID(data["id"])  # Valid UUID


@pytest.mark.asyncio
async def test_get_incident(client, sample_incident):
    """GET /api/v1/incidents/{id} returns the incident."""
    response = await client.get(f"/api/v1/incidents/{sample_incident.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(sample_incident.id)
    assert data["title"] == sample_incident.title
    assert data["severity"] == sample_incident.severity


@pytest.mark.asyncio
async def test_get_incident_not_found(client):
    """GET /api/v1/incidents/{id} returns 404 for unknown ID."""
    response = await client.get(f"/api/v1/incidents/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_incident(client, sample_incident):
    """PATCH /api/v1/incidents/{id} updates specified fields."""
    response = await client.patch(
        f"/api/v1/incidents/{sample_incident.id}",
        json={"status": "investigating", "severity": "P1"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "investigating"
    assert data["severity"] == "P1"


@pytest.mark.asyncio
async def test_delete_incident(client, sample_incident):
    """DELETE /api/v1/incidents/{id} removes the incident."""
    response = await client.delete(f"/api/v1/incidents/{sample_incident.id}")
    assert response.status_code == 204

    # Verify it's gone
    get_response = await client.get(f"/api/v1/incidents/{sample_incident.id}")
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_incident_not_found(client):
    """DELETE /api/v1/incidents/{id} returns 404 for unknown ID."""
    response = await client.delete(f"/api/v1/incidents/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_incidents_filter_by_severity(client, sample_incident):
    """GET /api/v1/incidents?severity=P2 filters correctly."""
    response = await client.get("/api/v1/incidents?severity=P2")
    assert response.status_code == 200
    data = response.json()
    assert all(i["severity"] == "P2" for i in data["items"])


@pytest.mark.asyncio
async def test_trigger_investigation(client, sample_incident):
    """POST /api/v1/incidents/{id}/investigate creates an investigation."""
    from unittest.mock import AsyncMock, patch

    with patch(
        "app.services.investigation_service.InvestigationService.run_investigation_background",
        new_callable=AsyncMock,
    ):
        response = await client.post(
            f"/api/v1/incidents/{sample_incident.id}/investigate",
            json={
                "query": "Why is the error rate high on checkout?",
                "time_window": {"start": "now-1h", "end": "now"},
                "created_by": "test@example.com",
            },
        )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "pending"
    assert data["incident_id"] == str(sample_incident.id)
    assert data["created_by"] == "test@example.com"
