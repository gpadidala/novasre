"""
WebSocket handler for the NovaSRE agent stream.
Endpoint: /ws/agent/{session_id}

Message flow:
  Client → Server:  { type: "message", payload: { content: "..." } }
  Server → Client:  thinking / tool_call / tool_result / finding / rca / done / error
"""
import asyncio
import json
import uuid
from typing import Any, Optional

import structlog
from fastapi import WebSocket, WebSocketDisconnect

import redis.asyncio as aioredis

from app.config import settings
from app.dependencies import get_redis_client
from app.schemas.agent import AgentMessageType

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Connection manager (tracks active WebSocket connections)
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Manages active WebSocket connections, keyed by session_id."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[session_id] = websocket
        log.info("websocket.connected", session_id=session_id)

    def disconnect(self, session_id: str) -> None:
        self._connections.pop(session_id, None)
        log.info("websocket.disconnected", session_id=session_id)

    async def send(self, session_id: str, message: dict) -> None:
        """Send a JSON message to a specific session."""
        ws = self._connections.get(session_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception as exc:
                log.warning(
                    "websocket.send_failed",
                    session_id=session_id,
                    error=str(exc),
                )
                self.disconnect(session_id)

    async def broadcast(self, message: dict) -> None:
        """Broadcast a message to all connected sessions."""
        for session_id in list(self._connections.keys()):
            await self.send(session_id, message)

    @property
    def active_sessions(self) -> list[str]:
        return list(self._connections.keys())


# Module-level connection manager (singleton)
manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Redis pub/sub helpers
# ---------------------------------------------------------------------------

PUBSUB_CHANNEL_PREFIX = "novasre:agent:"


def channel_name(session_id: str) -> str:
    return f"{PUBSUB_CHANNEL_PREFIX}{session_id}"


async def publish_to_session(session_id: str, message: dict) -> None:
    """Publish a message to a session's Redis pub/sub channel."""
    try:
        redis = await get_redis_client()
        await redis.publish(channel_name(session_id), json.dumps(message))
    except Exception as exc:
        log.error("redis.publish_failed", session_id=session_id, error=str(exc))


# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------

def make_message(
    msg_type: AgentMessageType,
    session_id: str,
    **payload: Any,
) -> dict:
    return {"type": msg_type.value, "session_id": session_id, **payload}


def thinking(session_id: str, agent: str, content: str, step: Optional[int] = None) -> dict:
    return make_message(
        AgentMessageType.THINKING,
        session_id,
        agent=agent,
        content=content,
        step=step,
    )


def tool_call_msg(
    session_id: str, tool: str, query: Optional[str], arguments: Optional[dict], call_id: str
) -> dict:
    return make_message(
        AgentMessageType.TOOL_CALL,
        session_id,
        tool=tool,
        query=query,
        arguments=arguments,
        call_id=call_id,
    )


def tool_result_msg(
    session_id: str,
    tool: str,
    call_id: str,
    success: bool,
    result: Any,
    error: Optional[str],
    duration_ms: Optional[float],
) -> dict:
    return make_message(
        AgentMessageType.TOOL_RESULT,
        session_id,
        tool=tool,
        call_id=call_id,
        success=success,
        result=result,
        error=error,
        duration_ms=duration_ms,
    )


def finding_msg(
    session_id: str, agent: str, content: str, data: Optional[dict] = None
) -> dict:
    return make_message(
        AgentMessageType.FINDING, session_id, agent=agent, content=content, data=data
    )


def rca_msg(
    session_id: str,
    content: str,
    confidence: float,
    recommended_actions: Optional[list] = None,
    affected_user_count: Optional[int] = None,
) -> dict:
    return make_message(
        AgentMessageType.RCA,
        session_id,
        content=content,
        confidence=confidence,
        recommended_actions=recommended_actions or [],
        affected_user_count=affected_user_count,
    )


def done_msg(session_id: str, investigation_id: Optional[str] = None) -> dict:
    return make_message(
        AgentMessageType.DONE, session_id, investigation_id=investigation_id
    )


def error_msg(session_id: str, code: str, message: str) -> dict:
    return make_message(
        AgentMessageType.ERROR, session_id, code=code, message=message
    )


# ---------------------------------------------------------------------------
# Core WebSocket handler
# ---------------------------------------------------------------------------


async def agent_websocket_handler(websocket: WebSocket, session_id: str) -> None:
    """
    Handle a WebSocket connection for the NovaSRE agent stream.

    Client sends:
      { "type": "message", "payload": { "content": "investigate checkout errors" } }
      { "type": "ping" }

    Server sends (in stream):
      thinking / tool_call / tool_result / finding / rca / done / error / pong
    """
    await manager.connect(session_id, websocket)

    # Subscribe to Redis pub/sub for this session (enables cross-process fanout)
    redis = await get_redis_client()
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel_name(session_id))

    # Start background task to forward Redis pub/sub → WebSocket
    pubsub_task = asyncio.create_task(
        _forward_pubsub_to_websocket(session_id, pubsub, websocket)
    )

    try:
        # Send a welcome / ready message
        await manager.send(
            session_id,
            {
                "type": "status",
                "session_id": session_id,
                "status": "connected",
                "message": f"NovaSRE agent session {session_id} is ready.",
            },
        )

        async for raw in websocket.iter_text():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send(
                    session_id,
                    error_msg(session_id, "INVALID_JSON", "Message must be valid JSON"),
                )
                continue

            msg_type = data.get("type", "")

            if msg_type == AgentMessageType.PING.value:
                await manager.send(
                    session_id,
                    {"type": AgentMessageType.PONG.value, "session_id": session_id},
                )

            elif msg_type == AgentMessageType.MESSAGE.value:
                payload = data.get("payload", {})
                content = payload.get("content", "")
                incident_id = payload.get("incident_id")

                log.info(
                    "websocket.message_received",
                    session_id=session_id,
                    incident_id=incident_id,
                    content_len=len(content),
                )

                # Run agent in background so we don't block the receive loop
                asyncio.create_task(
                    _handle_agent_message(
                        session_id=session_id,
                        content=content,
                        incident_id=incident_id,
                        extra_context=payload,
                    )
                )
            else:
                await manager.send(
                    session_id,
                    error_msg(
                        session_id,
                        "UNKNOWN_MESSAGE_TYPE",
                        f"Unknown message type: {msg_type!r}",
                    ),
                )

    except WebSocketDisconnect:
        log.info("websocket.client_disconnected", session_id=session_id)
    except Exception as exc:
        log.error("websocket.error", session_id=session_id, error=str(exc))
        try:
            await manager.send(
                session_id,
                error_msg(session_id, "INTERNAL_ERROR", str(exc)),
            )
        except Exception:
            pass
    finally:
        pubsub_task.cancel()
        await pubsub.unsubscribe(channel_name(session_id))
        await pubsub.aclose()
        manager.disconnect(session_id)


async def _forward_pubsub_to_websocket(
    session_id: str,
    pubsub: aioredis.client.PubSub,
    websocket: WebSocket,
) -> None:
    """Forward messages from Redis pub/sub to the WebSocket."""
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    await websocket.send_json(data)
                except Exception as exc:
                    log.warning(
                        "pubsub.forward_failed",
                        session_id=session_id,
                        error=str(exc),
                    )
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        log.error("pubsub.listener_error", session_id=session_id, error=str(exc))


async def _handle_agent_message(
    session_id: str,
    content: str,
    incident_id: Optional[str],
    extra_context: dict,
) -> None:
    """
    Process an incoming agent message.
    Phase 3 wires this to the LangGraph investigation graph.
    For Phase 1, sends a structured placeholder response.
    """
    try:
        # Acknowledge receipt
        await manager.send(
            session_id,
            thinking(session_id, "planner", "Analyzing your request...", step=1),
        )

        await asyncio.sleep(0.1)  # Simulate minimal processing

        # Phase 3: invoke LangGraph graph here
        # graph = build_investigation_graph()
        # result = await graph.ainvoke({...})

        response = (
            f"I received your message: \"{content[:100]}\". "
            "The full LangGraph multi-agent investigation system will be wired in Phase 3. "
            "For now, use POST /api/v1/incidents/{id}/investigate to trigger an RCA."
        )
        if incident_id:
            response = (
                f"Investigation for incident {incident_id} acknowledged. "
                "Use the REST endpoint to trigger a formal investigation: "
                f"POST /api/v1/incidents/{incident_id}/investigate"
            )

        await manager.send(
            session_id,
            rca_msg(
                session_id=session_id,
                content=response,
                confidence=0.0,
                recommended_actions=["Trigger formal investigation via REST API"],
            ),
        )
        await manager.send(session_id, done_msg(session_id))

    except Exception as exc:
        log.error(
            "agent.handler_error",
            session_id=session_id,
            error=str(exc),
            exc_info=True,
        )
        await manager.send(
            session_id,
            error_msg(session_id, "AGENT_ERROR", str(exc)),
        )
