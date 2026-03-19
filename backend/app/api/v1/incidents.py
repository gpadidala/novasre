"""
Incident CRUD endpoints + investigation trigger.
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import DbSession
from app.models.incident import Incident
from app.schemas.incident import (
    IncidentCreate,
    IncidentListResponse,
    IncidentResponse,
    IncidentUpdate,
)
from app.schemas.investigation import InvestigationRequest, InvestigationResponse
from app.services.incident_service import IncidentService
from app.services.investigation_service import InvestigationService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/incidents", tags=["incidents"])


def _to_response(incident: Incident) -> IncidentResponse:
    return IncidentResponse(
        id=incident.id,
        title=incident.title,
        description=incident.description,
        severity=incident.severity,
        status=incident.status,
        affected_services=incident.affected_services or [],
        start_time=incident.start_time,
        resolved_time=incident.resolved_time,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        investigation_count=len(incident.investigations) if incident.investigations else 0,
        alert_count=len(incident.alerts) if incident.alerts else 0,
    )


@router.get("", response_model=IncidentListResponse, summary="List incidents")
async def list_incidents(
    db: DbSession,
    severity: Optional[str] = Query(default=None, description="Filter by severity P1-P4"),
    status_filter: Optional[str] = Query(
        default=None, alias="status", description="Filter by status"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> IncidentListResponse:
    """List incidents with optional filtering and pagination."""
    service = IncidentService(db)
    incidents, total = await service.list_incidents(
        severity=severity,
        status=status_filter,
        page=page,
        page_size=page_size,
    )
    return IncidentListResponse(
        items=[_to_response(i) for i in incidents],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create incident",
)
async def create_incident(
    payload: IncidentCreate,
    db: DbSession,
) -> IncidentResponse:
    """Create a new incident."""
    service = IncidentService(db)
    incident = await service.create_incident(payload)
    log.info("incident.created", incident_id=str(incident.id), severity=incident.severity)
    return _to_response(incident)


@router.get("/{incident_id}", response_model=IncidentResponse, summary="Get incident")
async def get_incident(
    incident_id: uuid.UUID,
    db: DbSession,
) -> IncidentResponse:
    """Retrieve a single incident by ID."""
    service = IncidentService(db)
    incident = await service.get_incident(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )
    return _to_response(incident)


@router.patch(
    "/{incident_id}",
    response_model=IncidentResponse,
    summary="Update incident",
)
async def update_incident(
    incident_id: uuid.UUID,
    payload: IncidentUpdate,
    db: DbSession,
) -> IncidentResponse:
    """Partially update an incident."""
    service = IncidentService(db)
    incident = await service.update_incident(incident_id, payload)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )
    log.info("incident.updated", incident_id=str(incident_id))
    return _to_response(incident)


@router.delete(
    "/{incident_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete incident",
)
async def delete_incident(
    incident_id: uuid.UUID,
    db: DbSession,
) -> None:
    """Delete an incident and all associated investigations."""
    service = IncidentService(db)
    deleted = await service.delete_incident(incident_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )
    log.info("incident.deleted", incident_id=str(incident_id))


@router.post(
    "/{incident_id}/investigate",
    response_model=InvestigationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger RCA investigation",
)
async def trigger_investigation(
    incident_id: uuid.UUID,
    request: InvestigationRequest,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> InvestigationResponse:
    """
    Trigger a new RCA investigation for an incident.
    The investigation runs in the background; results stream via WebSocket /ws/agent/{session_id}.
    Returns the newly created Investigation object immediately (status=pending).
    """
    # Verify incident exists
    incident_service = IncidentService(db)
    incident = await incident_service.get_incident(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )

    inv_service = InvestigationService(db)
    investigation = await inv_service.create_investigation(
        incident_id=incident_id,
        request=request,
    )

    # Queue background execution
    background_tasks.add_task(
        inv_service.run_investigation_background,
        investigation_id=investigation.id,
        incident=incident,
        request=request,
    )

    log.info(
        "investigation.triggered",
        investigation_id=str(investigation.id),
        incident_id=str(incident_id),
        created_by=request.created_by,
    )

    return InvestigationResponse.model_validate(investigation)
