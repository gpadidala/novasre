"""
Pydantic v2 schemas for WebSocket agent communication and chat API.
"""
from typing import Any, Literal, Optional, Union
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# WebSocket message types
# ---------------------------------------------------------------------------

class AgentMessageType(str, Enum):
    """All message types that flow over the /ws/agent WebSocket."""
    # Client → Server
    MESSAGE = "message"          # User sends a question / instruction
    PING = "ping"                # Keepalive ping from client

    # Server → Client
    THINKING = "thinking"        # Agent is reasoning (which tools to use)
    TOOL_CALL = "tool_call"      # Agent is executing a tool
    TOOL_RESULT = "tool_result"  # Tool returned a result
    FINDING = "finding"          # A specialist agent published a finding
    RCA = "rca"                  # Final RCA report is ready
    STATUS = "status"            # Investigation status update
    ERROR = "error"              # An error occurred
    DONE = "done"                # Investigation / session complete
    PONG = "pong"                # Keepalive response


class WebSocketMessage(BaseModel):
    """
    Generic WebSocket message envelope.
    The `payload` field carries type-specific data.
    """
    type: AgentMessageType
    session_id: str
    payload: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Specific server-sent message schemas
# ---------------------------------------------------------------------------

class ThinkingMessage(BaseModel):
    """Agent is in a reasoning step."""
    type: Literal[AgentMessageType.THINKING] = AgentMessageType.THINKING
    agent: str = Field(..., description="Agent name: planner/metrics/logs/...")
    content: str = Field(..., description="What the agent is thinking about")
    step: Optional[int] = None


class ToolCallMessage(BaseModel):
    """Agent is invoking a tool."""
    type: Literal[AgentMessageType.TOOL_CALL] = AgentMessageType.TOOL_CALL
    tool: str = Field(..., description="Tool name, e.g. 'mimir_query'")
    query: Optional[str] = Field(default=None, description="The raw query / expression")
    arguments: Optional[dict[str, Any]] = Field(
        default=None, description="Full tool call arguments"
    )
    call_id: Optional[str] = None


class ToolResultMessage(BaseModel):
    """Tool execution returned a result."""
    type: Literal[AgentMessageType.TOOL_RESULT] = AgentMessageType.TOOL_RESULT
    tool: str
    call_id: Optional[str] = None
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: Optional[float] = None


class FindingMessage(BaseModel):
    """A specialist agent completed its investigation and produced a finding."""
    type: Literal[AgentMessageType.FINDING] = AgentMessageType.FINDING
    agent: str = Field(..., description="Agent name: metrics/logs/traces/...")
    content: str = Field(..., description="Natural language finding summary")
    data: Optional[dict[str, Any]] = Field(
        default=None, description="Structured finding data"
    )
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class RCAMessage(BaseModel):
    """Full RCA report from the Synthesizer agent."""
    type: Literal[AgentMessageType.RCA] = AgentMessageType.RCA
    content: str = Field(..., description="RCA report in Markdown format")
    confidence: float = Field(..., ge=0.0, le=1.0)
    recommended_actions: list[str] = Field(default_factory=list)
    affected_user_count: Optional[int] = None


class StatusMessage(BaseModel):
    """Investigation or system status update."""
    type: Literal[AgentMessageType.STATUS] = AgentMessageType.STATUS
    investigation_id: Optional[str] = None
    status: str
    message: Optional[str] = None


class ErrorMessage(BaseModel):
    """An error occurred."""
    type: Literal[AgentMessageType.ERROR] = AgentMessageType.ERROR
    code: str
    message: str
    details: Optional[dict[str, Any]] = None


class DoneMessage(BaseModel):
    """Investigation or session is complete."""
    type: Literal[AgentMessageType.DONE] = AgentMessageType.DONE
    investigation_id: Optional[str] = None
    summary: Optional[str] = None


# ---------------------------------------------------------------------------
# Chat endpoint schemas (REST fallback)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """POST /chat request body."""
    message: str = Field(..., min_length=1, description="User message")
    session_id: Optional[str] = Field(
        default=None, description="Session ID for conversation continuity"
    )
    incident_id: Optional[str] = Field(
        default=None, description="Associated incident ID if any"
    )
    context: Optional[dict[str, Any]] = Field(
        default=None, description="Additional context"
    )


class ChatResponse(BaseModel):
    """POST /chat response body."""
    session_id: str
    response: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    investigation_id: Optional[str] = None


# Type alias for incoming client messages
AgentMessage = Union[WebSocketMessage, ChatRequest]
