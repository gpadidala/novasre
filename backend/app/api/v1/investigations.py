"""
Investigation status and results endpoints.
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.dependencies import DbSession
from app.schemas.investigation import InvestigationResponse
from app.services.investigation_service import InvestigationService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.get(
    "",
    response_model=list[InvestigationResponse],
    summary="List investigations",
)
async def list_investigations(
    db: DbSession,
    incident_id: Optional[uuid.UUID] = Query(
        default=None, description="Filter by incident UUID"
    ),
    inv_status: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by status: pending, running, completed, failed",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[InvestigationResponse]:
    """List investigations, optionally filtered by incident or status."""
    service = InvestigationService(db)
    investigations = await service.list_investigations(
        incident_id=incident_id,
        status=inv_status,
        limit=limit,
        offset=offset,
    )
    return [InvestigationResponse.model_validate(i) for i in investigations]


@router.get(
    "/{investigation_id}",
    response_model=InvestigationResponse,
    summary="Get investigation by ID",
)
async def get_investigation(
    investigation_id: uuid.UUID,
    db: DbSession,
) -> InvestigationResponse:
    """Get the full investigation record including plan, findings, and RCA."""
    service = InvestigationService(db)
    investigation = await service.get_investigation(investigation_id)
    if not investigation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation {investigation_id} not found",
        )
    return InvestigationResponse.model_validate(investigation)


@router.get(
    "/{investigation_id}/rca",
    summary="Get RCA report",
    description="Returns the final RCA markdown for a completed investigation.",
)
async def get_rca(
    investigation_id: uuid.UUID,
    db: DbSession,
) -> dict:
    """Return only the RCA markdown from a completed investigation."""
    service = InvestigationService(db)
    investigation = await service.get_investigation(investigation_id)
    if not investigation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation {investigation_id} not found",
        )
    if investigation.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Investigation is in status '{investigation.status}', not yet completed",
        )
    return {
        "investigation_id": str(investigation_id),
        "rca": investigation.rca,
        "confidence": investigation.confidence,
        "completed_at": investigation.completed_at,
    }
