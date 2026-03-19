"""Pydantic v2 request/response schemas for NovaSRE API."""
from app.schemas.agent import (
    AgentMessage,
    AgentMessageType,
    ChatRequest,
    ChatResponse,
    WebSocketMessage,
)
from app.schemas.alert import (
    AlertCreate,
    AlertResponse,
    AlertUpdate,
    AlertmanagerWebhook,
    AlertmanagerWebhookAlert,
)
from app.schemas.incident import (
    IncidentCreate,
    IncidentListResponse,
    IncidentResponse,
    IncidentUpdate,
)
from app.schemas.investigation import (
    InvestigationRequest,
    InvestigationResponse,
    InvestigationUpdate,
)

__all__ = [
    # Incident
    "IncidentCreate",
    "IncidentUpdate",
    "IncidentResponse",
    "IncidentListResponse",
    # Alert
    "AlertCreate",
    "AlertUpdate",
    "AlertResponse",
    "AlertmanagerWebhook",
    "AlertmanagerWebhookAlert",
    # Investigation
    "InvestigationRequest",
    "InvestigationResponse",
    "InvestigationUpdate",
    # Agent / WebSocket
    "AgentMessage",
    "AgentMessageType",
    "ChatRequest",
    "ChatResponse",
    "WebSocketMessage",
]
