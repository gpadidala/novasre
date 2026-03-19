"""
REST chat endpoint — synchronous fallback when WebSocket is not available.
POST /chat — Send a message to the NovaSRE agent and get a response.
"""
import uuid

import structlog
from fastapi import APIRouter, HTTPException, status

from app.dependencies import DbSession, RedisDep
from app.schemas.agent import ChatRequest, ChatResponse

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "",
    response_model=ChatResponse,
    summary="Chat with the NovaSRE agent",
    description=(
        "Synchronous chat endpoint. For streaming responses, use the "
        "WebSocket at /ws/agent/{session_id}."
    ),
)
async def chat(
    request: ChatRequest,
    db: DbSession,
    redis: RedisDep,
) -> ChatResponse:
    """
    Send a message to the NovaSRE agent.
    Phase 3 will wire this to the full LangGraph investigation graph.
    For now, returns a structured placeholder acknowledging the message.
    """
    session_id = request.session_id or str(uuid.uuid4())

    log.info(
        "chat.message_received",
        session_id=session_id,
        incident_id=request.incident_id,
        message_len=len(request.message),
    )

    # Store session context in Redis for WebSocket continuity
    session_key = f"chat:session:{session_id}"
    await redis.hset(
        session_key,
        mapping={
            "last_message": request.message[:500],  # Truncate for storage
            "incident_id": request.incident_id or "",
        },
    )
    await redis.expire(session_key, 3600)  # 1 hour TTL

    # Phase 3: invoke LangGraph investigation graph here
    # For Phase 1, return acknowledgment
    response_text = (
        f"Message received. Session: {session_id}. "
        "The NovaSRE investigation agent will be available in Phase 3 "
        "when the LangGraph multi-agent system is wired in. "
        "For now, use the REST endpoints to manage incidents and trigger investigations."
    )

    if request.incident_id:
        response_text = (
            f"I've noted your question about incident {request.incident_id}. "
            "Use POST /api/v1/incidents/{id}/investigate to trigger a full RCA investigation. "
            "Results will stream via WebSocket /ws/agent/{session_id}."
        )

    return ChatResponse(
        session_id=session_id,
        response=response_text,
        tool_calls=[],
        investigation_id=None,
    )


@router.get(
    "/sessions/{session_id}",
    summary="Get chat session context",
)
async def get_session(
    session_id: str,
    redis: RedisDep,
) -> dict:
    """Retrieve the stored context for a chat session."""
    session_key = f"chat:session:{session_id}"
    data = await redis.hgetall(session_key)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found or expired",
        )
    return {"session_id": session_id, **data}
