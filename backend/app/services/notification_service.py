"""
NotificationService — sends notifications for incident and investigation events.
Supports: WebSocket pub/sub (immediate), Slack (Phase 8+), PagerDuty (Phase 8+).
"""
import json
import uuid
from typing import Any, Optional

import structlog

from app.config import settings

log = structlog.get_logger(__name__)


class NotificationService:
    """
    Handles all outbound notifications.
    Phase 1: WebSocket Redis pub/sub fanout only.
    Phase 8+: Slack, PagerDuty, email integrations.
    """

    def __init__(self) -> None:
        self._redis_client = None

    async def _get_redis(self):
        """Lazy-initialize Redis client."""
        if self._redis_client is None:
            from app.dependencies import get_redis_client
            self._redis_client = await get_redis_client()
        return self._redis_client

    # ------------------------------------------------------------------
    # WebSocket / pub/sub notifications
    # ------------------------------------------------------------------

    async def notify_incident_created(self, incident_id: uuid.UUID, title: str, severity: str) -> None:
        """Broadcast new incident creation to all connected WebSocket clients."""
        await self._broadcast(
            {
                "type": "incident_created",
                "incident_id": str(incident_id),
                "title": title,
                "severity": severity,
            }
        )

    async def notify_incident_updated(
        self,
        incident_id: uuid.UUID,
        changes: dict[str, Any],
    ) -> None:
        """Broadcast incident status/severity update."""
        await self._broadcast(
            {
                "type": "incident_updated",
                "incident_id": str(incident_id),
                "changes": changes,
            }
        )

    async def notify_investigation_status(
        self,
        investigation_id: uuid.UUID,
        incident_id: uuid.UUID,
        status: str,
        message: Optional[str] = None,
    ) -> None:
        """Notify relevant WebSocket sessions of investigation progress."""
        channel = f"novasre:agent:{investigation_id}"
        redis = await self._get_redis()
        payload = {
            "type": "status",
            "session_id": str(investigation_id),
            "investigation_id": str(investigation_id),
            "incident_id": str(incident_id),
            "status": status,
            "message": message,
        }
        try:
            await redis.publish(channel, json.dumps(payload))
        except Exception as exc:
            log.error(
                "notification_service.publish_failed",
                channel=channel,
                error=str(exc),
            )

    async def notify_alert_received(
        self, alert_id: uuid.UUID, name: str, severity: str, service: str
    ) -> None:
        """Broadcast new alert to all connected clients."""
        await self._broadcast(
            {
                "type": "alert_received",
                "alert_id": str(alert_id),
                "name": name,
                "severity": severity,
                "service": service,
            }
        )

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        """Publish to the global broadcast channel (all WebSocket clients)."""
        channel = "novasre:broadcast"
        redis = await self._get_redis()
        try:
            await redis.publish(channel, json.dumps(payload))
        except Exception as exc:
            log.error(
                "notification_service.broadcast_failed",
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Future integrations (Phase 8+)
    # ------------------------------------------------------------------

    async def send_slack_notification(
        self, channel: str, message: str, blocks: Optional[list] = None
    ) -> None:
        """
        Send a Slack notification.
        Phase 8: implement with slack_sdk.
        """
        log.info(
            "notification_service.slack_stub",
            channel=channel,
            message=message[:100],
        )

    async def send_pagerduty_event(
        self,
        routing_key: str,
        summary: str,
        severity: str,
        source: str,
        dedup_key: Optional[str] = None,
    ) -> None:
        """
        Send a PagerDuty event.
        Phase 8: implement with pdpyras.
        """
        log.info(
            "notification_service.pagerduty_stub",
            summary=summary[:100],
            severity=severity,
        )
