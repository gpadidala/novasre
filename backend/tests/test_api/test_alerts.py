"""
Tests for the Alerts API and Alertmanager webhook.
"""
import uuid
from datetime import datetime, timezone

import pytest


ALERTMANAGER_PAYLOAD = {
    "version": "4",
    "groupKey": "{}:{alertname='HighErrorRate'}",
    "truncatedAlerts": 0,
    "status": "firing",
    "receiver": "novasre",
    "groupLabels": {"alertname": "HighErrorRate"},
    "commonLabels": {"app": "checkout", "severity": "critical"},
    "commonAnnotations": {
        "summary": "Error rate > 5% on checkout",
        "description": "Current error rate is 12.3%",
    },
    "externalURL": "http://alertmanager.example.com",
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "HighErrorRate",
                "app": "checkout",
                "severity": "critical",
                "namespace": "production",
            },
            "annotations": {
                "summary": "Error rate > 5% on checkout",
                "runbook_url": "https://runbooks.example.com/checkout",
            },
            "startsAt": datetime.now(tz=timezone.utc).isoformat(),
            "endsAt": "0001-01-01T00:00:00Z",
            "generatorURL": "http://prometheus.example.com/...",
            "fingerprint": "abc123def456789012",
        }
    ],
}


@pytest.mark.asyncio
async def test_alertmanager_webhook_accepted(client):
    """POST /api/v1/alerts/webhook/alertmanager returns 202 immediately."""
    from unittest.mock import AsyncMock, patch

    with patch(
        "app.services.alert_service.AlertService.process_incoming_alerts",
        new_callable=AsyncMock,
    ):
        response = await client.post(
            "/api/v1/alerts/webhook/alertmanager",
            json=ALERTMANAGER_PAYLOAD,
        )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "accepted"
    assert data["count"] == 1


@pytest.mark.asyncio
async def test_list_alerts_empty(client):
    """GET /api/v1/alerts returns empty list when no alerts exist."""
    response = await client.get("/api/v1/alerts")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_alerts_with_data(client, sample_alert):
    """GET /api/v1/alerts returns alerts."""
    response = await client.get("/api/v1/alerts?status=firing")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["name"] == sample_alert.name


@pytest.mark.asyncio
async def test_get_alert_by_id(client, sample_alert):
    """GET /api/v1/alerts/{id} returns the alert."""
    response = await client.get(f"/api/v1/alerts/{sample_alert.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(sample_alert.id)
    assert data["name"] == sample_alert.name
    assert data["fingerprint"] == sample_alert.fingerprint


@pytest.mark.asyncio
async def test_get_alert_not_found(client):
    """GET /api/v1/alerts/{id} returns 404 for unknown ID."""
    response = await client.get(f"/api/v1/alerts/{uuid.uuid4()}")
    assert response.status_code == 404
