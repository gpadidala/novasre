"""
Pydantic v2 schemas for Incident CRUD operations.
"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class IncidentBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=512, description="Incident title")
    description: str = Field(default="", description="Full incident description")
    severity: str = Field(
        default="P3",
        pattern="^P[1-4]$",
        description="Severity level: P1 (critical) to P4 (low)",
    )
    status: str = Field(
        default="open",
        pattern="^(open|investigating|resolved|closed)$",
        description="Incident lifecycle status",
    )
    affected_services: list[str] = Field(
        default_factory=list, description="List of affected service names"
    )
    start_time: datetime = Field(..., description="When the incident started")
    resolved_time: Optional[datetime] = Field(
        default=None, description="When the incident was resolved"
    )


class IncidentCreate(IncidentBase):
    """Request body for POST /incidents."""
    pass


class IncidentUpdate(BaseModel):
    """Request body for PATCH /incidents/{id}. All fields optional."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=512)
    description: Optional[str] = None
    severity: Optional[str] = Field(default=None, pattern="^P[1-4]$")
    status: Optional[str] = Field(
        default=None, pattern="^(open|investigating|resolved|closed)$"
    )
    affected_services: Optional[list[str]] = None
    start_time: Optional[datetime] = None
    resolved_time: Optional[datetime] = None


class IncidentResponse(IncidentBase):
    """Response body for incident endpoints."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    # Lightweight summaries to avoid N+1 loads
    investigation_count: int = Field(default=0, description="Number of investigations")
    alert_count: int = Field(default=0, description="Number of associated alerts")


class IncidentListResponse(BaseModel):
    """Paginated list of incidents."""
    items: list[IncidentResponse]
    total: int
    page: int = 1
    page_size: int = 50
