"""
Pydantic v2 schemas for Investigation operations.
"""
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class TimeWindow(BaseModel):
    """Time window for investigation queries."""
    start: str = Field(
        default="now-1h",
        description="Start time (ISO8601, Unix ts, or relative like 'now-1h')",
    )
    end: str = Field(
        default="now",
        description="End time (ISO8601, Unix ts, or relative like 'now')",
    )


class InvestigationRequest(BaseModel):
    """
    Request body for POST /incidents/{id}/investigate.
    All fields are optional — the Planner agent will determine scope if omitted.
    """
    query: str = Field(
        default="",
        description="Natural language question / investigation scope",
    )
    time_window: TimeWindow = Field(
        default_factory=TimeWindow,
        description="Time window to investigate",
    )
    focus_signals: Optional[list[str]] = Field(
        default=None,
        description="Restrict investigation to specific signals: metrics/logs/traces/profiles/frontend/k8s",
    )
    context: Optional[dict[str, Any]] = Field(
        default=None,
        description="Additional context to pass to the Planner agent",
    )
    created_by: str = Field(
        default="user",
        description="Who triggered this investigation",
    )


class InvestigationUpdate(BaseModel):
    """Internal: used by services to update investigation progress."""
    status: Optional[str] = Field(
        default=None,
        pattern="^(pending|running|completed|failed)$",
    )
    plan: Optional[dict[str, Any]] = None
    findings: Optional[dict[str, Any]] = None
    rca: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    tool_calls: Optional[list[Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class InvestigationResponse(BaseModel):
    """Investigation API response."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    status: str
    plan: Optional[dict[str, Any]] = None
    findings: Optional[dict[str, Any]] = None
    rca: Optional[str] = None
    confidence: Optional[float] = None
    tool_calls: Optional[list[Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_by: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
