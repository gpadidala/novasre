"""
AlertService — ingestion, deduplication, correlation, and incident linkage.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.alert import Alert
from app.schemas.alert import AlertmanagerWebhookAlert

log = structlog.get_logger(__name__)


class AlertService:
    """Handles all Alert-related business logic."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_alert(self, alert_id: uuid.UUID) -> Optional[Alert]:
        result = await self.db.execute(select(Alert).where(Alert.id == alert_id))
        return result.scalar_one_or_none()

    async def get_by_fingerprint(self, fingerprint: str) -> Optional[Alert]:
        result = await self.db.execute(
            select(Alert).where(Alert.fingerprint == fingerprint)
        )
        return result.scalar_one_or_none()

    async def list_alerts(
        self,
        status: Optional[str] = None,
        service: Optional[str] = None,
        incident_id: Optional[uuid.UUID] = None,
        severity: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Alert]:
        stmt = select(Alert)
        if status:
            stmt = stmt.where(Alert.status == status)
        if incident_id:
            stmt = stmt.where(Alert.incident_id == incident_id)
        if severity:
            stmt = stmt.where(Alert.severity == severity)
        if service:
            # Service name appears in alert labels
            stmt = stmt.where(Alert.labels["app"].astext == service)

        stmt = (
            stmt.order_by(Alert.fired_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_firing_alerts(self) -> list[Alert]:
        result = await self.db.execute(
            select(Alert).where(Alert.status == "firing").order_by(Alert.fired_at.desc())
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Ingestion pipeline
    # ------------------------------------------------------------------

    async def process_incoming_alerts(
        self, raw_alerts: list[AlertmanagerWebhookAlert]
    ) -> list[Alert]:
        """
        Full alert processing pipeline:
        1. Parse and persist raw alerts (with deduplication)
        2. Run 3-layer correlation engine (Phase 4)
        3. Create/update incidents for correlated groups
        4. Auto-trigger investigation for P1s (Phase 4+)
        5. Publish to Redis pub/sub for WebSocket fanout
        """
        persisted: list[Alert] = []

        for raw in raw_alerts:
            alert = await self._upsert_alert(raw)
            if alert:
                persisted.append(alert)

        if persisted:
            await self.db.commit()
            log.info(
                "alert_service.batch_processed",
                count=len(persisted),
                firing=[a.name for a in persisted if a.status == "firing"],
            )

            # Phase 4: run correlation engine and create incidents
            await self._correlate_and_group(persisted)

        return persisted

    async def _upsert_alert(self, raw: AlertmanagerWebhookAlert) -> Optional[Alert]:
        """
        Insert a new alert or update an existing one (deduplication by fingerprint).
        Returns the persisted Alert, or None if nothing changed.
        """
        existing = await self.get_by_fingerprint(raw.fingerprint)

        if existing:
            # Update status / resolved_at
            if raw.status == "resolved" and existing.status == "firing":
                existing.status = "resolved"
                existing.resolved_at = raw.endsAt or datetime.now(tz=timezone.utc)
                await self.db.flush()
                log.info(
                    "alert_service.resolved",
                    fingerprint=raw.fingerprint,
                    name=existing.name,
                )
            return existing

        # Extract service name from labels for naming
        service = (
            raw.labels.get("app")
            or raw.labels.get("service")
            or raw.labels.get("job")
            or "unknown"
        )
        alert_name = raw.labels.get("alertname", raw.fingerprint[:16])
        severity = raw.labels.get("severity", "warning")

        alert = Alert(
            name=alert_name,
            fingerprint=raw.fingerprint,
            labels=dict(raw.labels),
            annotations=dict(raw.annotations),
            severity=severity,
            status=raw.status,
            source="alertmanager",
            fired_at=raw.startsAt,
            resolved_at=raw.endsAt if raw.status == "resolved" else None,
        )
        self.db.add(alert)
        await self.db.flush()
        await self.db.refresh(alert)

        log.info(
            "alert_service.ingested",
            alert_id=str(alert.id),
            name=alert_name,
            severity=severity,
            service=service,
        )
        return alert

    async def _correlate_and_group(self, alerts: list[Alert]) -> None:
        """
        Stub for Phase 4's 3-layer correlation engine.
        Phase 4 will replace this with:
          groups = await correlation_engine.correlate(alerts)
          for group in groups:
              incident = await incident_service.get_or_create_from_alert_group(...)
              await self._link_group_to_incident(group, incident)
        """
        from app.services.incident_service import IncidentService

        for alert in alerts:
            if alert.status == "firing" and not alert.incident_id:
                severity = self._map_severity(alert.severity)
                service = (
                    alert.labels.get("app")
                    or alert.labels.get("service")
                    or alert.labels.get("job")
                    or "unknown"
                )

                incident_svc = IncidentService(self.db)
                incident = await incident_svc.get_or_create_from_alert_group(
                    title=f"{alert.name} on {service}",
                    severity=severity,
                    affected_services=[service],
                    start_time=alert.fired_at,
                )
                alert.incident_id = incident.id
                await self.db.flush()

    @staticmethod
    def _map_severity(alert_severity: str) -> str:
        """Map Prometheus severity labels to P-levels."""
        mapping = {
            "critical": "P1",
            "error": "P2",
            "warning": "P3",
            "info": "P4",
        }
        return mapping.get(alert_severity.lower(), "P3")

    async def suppress_alert(self, alert_id: uuid.UUID) -> Optional[Alert]:
        """Mark an alert as suppressed (noise reduction)."""
        alert = await self.get_alert(alert_id)
        if not alert:
            return None
        alert.status = "suppressed"
        await self.db.flush()
        return alert
