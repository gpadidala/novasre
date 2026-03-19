"""
Pydantic v2 schemas for Alert ingestion and querying.
Includes Alertmanager webhook payload parsing.
"""
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Alertmanager webhook format
# ---------------------------------------------------------------------------

class AlertmanagerWebhookAlert(BaseModel):
    """A single alert inside an Alertmanager webhook payload."""
    status: str = Field(..., description="'firing' or 'resolved'")
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    endsAt: Optional[datetime] = None
    generatorURL: str = Field(default="")
    fingerprint: str = Field(..., description="Alertmanager dedup fingerprint")


class AlertmanagerWebhook(BaseModel):
    """Full Alertmanager webhook payload (POST /webhook/alertmanager)."""
    version: str = Field(default="4")
    groupKey: str = Field(default="")
    truncatedAlerts: int = Field(default=0)
    status: str = Field(default="firing")
    receiver: str = Field(default="novasre")
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str = Field(default="")
    alerts: list[AlertmanagerWebhookAlert] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Alert CRUD schemas
# ---------------------------------------------------------------------------

class AlertBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=512)
    fingerprint: str = Field(..., max_length=128)
    labels: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)
    severity: str = Field(default="warning", max_length=32)
    status: str = Field(
        default="firing", pattern="^(firing|resolved|suppressed)$"
    )
    source: str = Field(default="alertmanager", max_length=64)
    fired_at: datetime
    resolved_at: Optional[datetime] = None
    incident_id: Optional[uuid.UUID] = None
    correlation_group_id: Optional[uuid.UUID] = None


class AlertCreate(AlertBase):
    """Request body for creating a single alert (internal use)."""
    pass


class AlertUpdate(BaseModel):
    """Partial update for an alert."""
    status: Optional[str] = Field(
        default=None, pattern="^(firing|resolved|suppressed)$"
    )
    resolved_at: Optional[datetime] = None
    incident_id: Optional[uuid.UUID] = None
    correlation_group_id: Optional[uuid.UUID] = None


class AlertResponse(AlertBase):
    """Alert API response."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
