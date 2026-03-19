"""
InvestigationService — manages Investigation lifecycle and executes RCA.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.models.investigation import Investigation
from app.schemas.investigation import InvestigationRequest, InvestigationUpdate

log = structlog.get_logger(__name__)


class InvestigationService:
    """Handles Investigation creation, querying, and execution."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_investigation(
        self, investigation_id: uuid.UUID
    ) -> Optional[Investigation]:
        result = await self.db.execute(
            select(Investigation).where(Investigation.id == investigation_id)
        )
        return result.scalar_one_or_none()

    async def list_investigations(
        self,
        incident_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Investigation]:
        stmt = select(Investigation)
        if incident_id:
            stmt = stmt.where(Investigation.incident_id == incident_id)
        if status:
            stmt = stmt.where(Investigation.status == status)
        stmt = (
            stmt.order_by(Investigation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def create_investigation(
        self,
        incident_id: uuid.UUID,
        request: InvestigationRequest,
    ) -> Investigation:
        """Create a new Investigation record in 'pending' status."""
        investigation = Investigation(
            incident_id=incident_id,
            status="pending",
            created_by=request.created_by,
            tool_calls=[],
        )
        self.db.add(investigation)
        await self.db.flush()
        await self.db.refresh(investigation)
        log.info(
            "investigation_service.created",
            investigation_id=str(investigation.id),
            incident_id=str(incident_id),
        )
        return investigation

    async def update_investigation(
        self,
        investigation_id: uuid.UUID,
        update: InvestigationUpdate,
    ) -> Optional[Investigation]:
        """Apply a partial update to an Investigation."""
        investigation = await self.get_investigation(investigation_id)
        if not investigation:
            return None

        update_data = update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(investigation, field, value)

        await self.db.flush()
        await self.db.refresh(investigation)
        return investigation

    # ------------------------------------------------------------------
    # Background execution
    # ------------------------------------------------------------------

    async def run_investigation_background(
        self,
        investigation_id: uuid.UUID,
        incident: Incident,
        request: InvestigationRequest,
    ) -> None:
        """
        Execute the full RCA investigation in the background.
        Phase 3 will replace the placeholder logic with the LangGraph graph.
        Progress is streamed to the WebSocket channel via Redis pub/sub.
        """
        # We need a fresh DB session since we're in a background task
        from app.database import AsyncSessionLocal
        from app.api.websocket import publish_to_session

        session_id = str(investigation_id)  # Use investigation_id as session channel

        async with AsyncSessionLocal() as db:
            inv_service = InvestigationService(db)
            inv = await inv_service.get_investigation(investigation_id)
            if not inv:
                log.error(
                    "investigation_service.not_found",
                    investigation_id=str(investigation_id),
                )
                return

            # Mark as running
            await inv_service.update_investigation(
                investigation_id,
                InvestigationUpdate(
                    status="running",
                    started_at=datetime.now(tz=timezone.utc),
                ),
            )
            await db.commit()

            await publish_to_session(
                session_id,
                {
                    "type": "status",
                    "session_id": session_id,
                    "investigation_id": str(investigation_id),
                    "status": "running",
                    "message": "Investigation started",
                },
            )

            try:
                # Phase 3: call LangGraph graph
                # graph = build_investigation_graph()
                # result = await graph.ainvoke({
                #     "incident_id": str(incident.id),
                #     "query": request.query,
                #     "affected_services": incident.affected_services or [],
                #     "time_window": request.time_window.model_dump(),
                #     "alert_context": {},
                # })
                # rca = result["rca"]
                # confidence = result.get("confidence", 0.5)

                # Phase 1 placeholder
                await asyncio.sleep(2)
                rca = self._generate_placeholder_rca(incident, request)
                confidence = 0.0

                await inv_service.update_investigation(
                    investigation_id,
                    InvestigationUpdate(
                        status="completed",
                        rca=rca,
                        confidence=confidence,
                        completed_at=datetime.now(tz=timezone.utc),
                    ),
                )
                await db.commit()

                await publish_to_session(
                    session_id,
                    {
                        "type": "rca",
                        "session_id": session_id,
                        "investigation_id": str(investigation_id),
                        "content": rca,
                        "confidence": confidence,
                        "recommended_actions": [
                            "Review agent findings in Phase 3",
                            "Enable LangGraph multi-agent system",
                        ],
                    },
                )
                await publish_to_session(
                    session_id,
                    {
                        "type": "done",
                        "session_id": session_id,
                        "investigation_id": str(investigation_id),
                    },
                )
                log.info(
                    "investigation_service.completed",
                    investigation_id=str(investigation_id),
                )

            except Exception as exc:
                log.error(
                    "investigation_service.failed",
                    investigation_id=str(investigation_id),
                    error=str(exc),
                    exc_info=True,
                )
                await inv_service.update_investigation(
                    investigation_id,
                    InvestigationUpdate(
                        status="failed",
                        error_message=str(exc),
                        completed_at=datetime.now(tz=timezone.utc),
                    ),
                )
                await db.commit()

                await publish_to_session(
                    session_id,
                    {
                        "type": "error",
                        "session_id": session_id,
                        "investigation_id": str(investigation_id),
                        "code": "INVESTIGATION_FAILED",
                        "message": str(exc),
                    },
                )

    @staticmethod
    def _generate_placeholder_rca(
        incident: Incident, request: InvestigationRequest
    ) -> str:
        """
        Phase 1 placeholder RCA. Phase 3 replaces with LangGraph synthesizer.
        """
        services = ", ".join(incident.affected_services or ["unknown"])
        return f"""## Incident Summary

**Incident:** {incident.title}
**Severity:** {incident.severity}
**Affected Services:** {services}
**Query:** {request.query or "General investigation"}

## Status

This is a Phase 1 placeholder investigation. The full LangGraph multi-agent
RCA engine will be implemented in Phase 3.

## What will happen in Phase 3

The investigation graph will:
1. **Planner Agent** — Analyze the incident and create a targeted investigation plan
2. **Metrics Agent** — Query Mimir for RED metrics (Rate, Errors, Duration)
3. **Logs Agent** — Extract error patterns from Loki
4. **Traces Agent** — Find slow/error traces in Tempo
5. **Profiles Agent** — Check CPU/memory profiles in Pyroscope
6. **Frontend Agent** — Check Core Web Vitals in Faro
7. **Synthesizer Agent** — Produce this RCA with root cause and recommendations

## Recommended Actions

1. Trigger this investigation again after Phase 3 is deployed
2. Ensure Mimir, Loki, Tempo, and Pyroscope are configured
3. Add service topology in the Services table for topological correlation
"""
