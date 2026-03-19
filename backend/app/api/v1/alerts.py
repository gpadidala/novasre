"""
Alert ingestion and querying endpoints.
POST /alerts/webhook/alertmanager — Alertmanager webhook receiver
GET  /alerts                       — List/search alerts
GET  /alerts/{id}                  — Get single alert
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.dependencies import DbSession
from app.schemas.alert import AlertmanagerWebhook, AlertResponse
from app.services.alert_service import AlertService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post(
    "/webhook/alertmanager",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Alertmanager webhook receiver",
    description=(
        "Receives Alertmanager POST webhooks. "
        "Persists, deduplicates, correlates, and potentially creates incidents. "
        "Always returns 202 immediately — processing happens in the background."
    ),
)
async def receive_alertmanager_webhook(
    payload: AlertmanagerWebhook,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> dict:
    """
    Receive Alertmanager webhook → persist → correlate → maybe create incident.
    Returns immediately with 202 to meet Alertmanager's timeout requirements (<200ms).
    """
    log.info(
        "alertmanager.webhook_received",
        alert_count=len(payload.alerts),
        status=payload.status,
        receiver=payload.receiver,
    )
    alert_service = AlertService(db)
    background_tasks.add_task(
        alert_service.process_incoming_alerts,
        payload.alerts,
    )
    return {"status": "accepted", "count": len(payload.alerts)}


@router.get(
    "",
    response_model=list[AlertResponse],
    summary="List alerts",
)
async def list_alerts(
    db: DbSession,
    alert_status: Optional[str] = Query(
        default="firing",
        alias="status",
        description="Filter by status: firing, resolved, suppressed",
    ),
    service: Optional[str] = Query(
        default=None, description="Filter by service name in labels"
    ),
    incident_id: Optional[uuid.UUID] = Query(
        default=None, description="Filter by incident ID"
    ),
    severity: Optional[str] = Query(default=None, description="Filter by severity"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AlertResponse]:
    """List alerts with filtering options."""
    alert_service = AlertService(db)
    alerts = await alert_service.list_alerts(
        status=alert_status,
        service=service,
        incident_id=incident_id,
        severity=severity,
        limit=limit,
        offset=offset,
    )
    return [AlertResponse.model_validate(a) for a in alerts]


@router.get(
    "/{alert_id}",
    response_model=AlertResponse,
    summary="Get alert by ID",
)
async def get_alert(
    alert_id: uuid.UUID,
    db: DbSession,
) -> AlertResponse:
    """Retrieve a single alert by UUID."""
    alert_service = AlertService(db)
    alert = await alert_service.get_alert(alert_id)
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found",
        )
    return AlertResponse.model_validate(alert)
