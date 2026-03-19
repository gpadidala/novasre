"""
IncidentService — all business logic for Incident lifecycle management.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.schemas.incident import IncidentCreate, IncidentUpdate

log = structlog.get_logger(__name__)


class IncidentService:
    """Encapsulates all Incident-related DB operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_incident(self, incident_id: uuid.UUID) -> Optional[Incident]:
        """Return a single Incident by ID, or None if not found."""
        result = await self.db.execute(
            select(Incident).where(Incident.id == incident_id)
        )
        return result.scalar_one_or_none()

    async def list_incidents(
        self,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Incident], int]:
        """
        Return paginated incidents and total count.
        Filters are AND-combined when multiple are provided.
        """
        stmt = select(Incident)
        count_stmt = select(func.count()).select_from(Incident)

        if severity:
            stmt = stmt.where(Incident.severity == severity)
            count_stmt = count_stmt.where(Incident.severity == severity)
        if status:
            stmt = stmt.where(Incident.status == status)
            count_stmt = count_stmt.where(Incident.status == status)

        stmt = (
            stmt.order_by(Incident.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        result = await self.db.execute(stmt)
        count_result = await self.db.execute(count_stmt)

        incidents = result.scalars().all()
        total = count_result.scalar() or 0
        return list(incidents), total

    async def get_active_incidents(self) -> list[Incident]:
        """Return all open or investigating incidents."""
        result = await self.db.execute(
            select(Incident)
            .where(Incident.status.in_(["open", "investigating"]))
            .order_by(Incident.severity, Incident.created_at.desc())
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def create_incident(self, payload: IncidentCreate) -> Incident:
        """Persist a new Incident and return it."""
        incident = Incident(
            title=payload.title,
            description=payload.description,
            severity=payload.severity,
            status=payload.status,
            affected_services=payload.affected_services,
            start_time=payload.start_time,
            resolved_time=payload.resolved_time,
        )
        self.db.add(incident)
        await self.db.flush()
        await self.db.refresh(incident)
        log.info(
            "incident_service.created",
            incident_id=str(incident.id),
            severity=incident.severity,
            title=incident.title[:60],
        )
        return incident

    async def update_incident(
        self, incident_id: uuid.UUID, payload: IncidentUpdate
    ) -> Optional[Incident]:
        """Partially update an Incident. Returns None if not found."""
        incident = await self.get_incident(incident_id)
        if not incident:
            return None

        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(incident, field, value)

        # Auto-set resolved_time when status transitions to resolved/closed
        if payload.status in ("resolved", "closed") and not incident.resolved_time:
            incident.resolved_time = datetime.now(tz=timezone.utc)

        await self.db.flush()
        await self.db.refresh(incident)
        log.info("incident_service.updated", incident_id=str(incident_id))
        return incident

    async def delete_incident(self, incident_id: uuid.UUID) -> bool:
        """Delete an Incident and cascade to investigations. Returns False if not found."""
        incident = await self.get_incident(incident_id)
        if not incident:
            return False
        await self.db.delete(incident)
        await self.db.flush()
        log.info("incident_service.deleted", incident_id=str(incident_id))
        return True

    async def link_alert(self, incident_id: uuid.UUID, alert_id: uuid.UUID) -> bool:
        """Link an Alert to this Incident."""
        from app.models.alert import Alert

        result = await self.db.execute(
            select(Alert).where(Alert.id == alert_id)
        )
        alert = result.scalar_one_or_none()
        if not alert:
            return False

        alert.incident_id = incident_id
        await self.db.flush()
        return True

    async def get_or_create_from_alert_group(
        self,
        title: str,
        severity: str,
        affected_services: list[str],
        start_time: datetime,
    ) -> Incident:
        """
        Find an existing open incident for these services or create a new one.
        Used by the alert correlation engine to auto-create incidents.
        """
        # Look for an existing open incident for any of these services
        # Simple strategy: if any service already has an open incident, reuse it
        result = await self.db.execute(
            select(Incident).where(
                Incident.status.in_(["open", "investigating"])
            ).order_by(Incident.created_at.desc()).limit(1)
        )
        existing = result.scalar_one_or_none()

        # Check if affected services overlap
        if existing:
            existing_services = set(existing.affected_services or [])
            new_services = set(affected_services)
            if existing_services & new_services:
                # Merge: add new services to existing incident
                merged = list(existing_services | new_services)
                existing.affected_services = merged
                if severity < existing.severity:  # P1 < P2 < P3 < P4 lexicographically
                    existing.severity = severity
                await self.db.flush()
                return existing

        # Create a new incident
        incident = Incident(
            title=title,
            description="Auto-created from correlated alert group",
            severity=severity,
            status="open",
            affected_services=affected_services,
            start_time=start_time,
        )
        self.db.add(incident)
        await self.db.flush()
        await self.db.refresh(incident)
        log.info(
            "incident_service.auto_created",
            incident_id=str(incident.id),
            title=title,
        )
        return incident
