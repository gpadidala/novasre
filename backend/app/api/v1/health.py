"""
Health and readiness probe endpoints.
GET /health        — liveness probe: is the process alive?
GET /health/ready  — readiness probe: can it serve traffic (DB + Redis up)?
"""
from typing import Literal

import structlog
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.database import check_db_connection
from app.dependencies import check_redis_connection

log = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    db: Literal["ok", "error"]
    redis: Literal["ok", "error"]
    version: str = "0.1.0"


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Returns 200 if the process is alive. Does not check dependencies.",
)
async def liveness() -> HealthResponse:
    """
    Kubernetes liveness probe.
    Always returns 200 as long as the process is running.
    """
    return HealthResponse(status="ok", db="ok", redis="ok")


@router.get(
    "/health/ready",
    summary="Readiness probe",
    description="Returns 200 if DB and Redis are reachable, 503 otherwise.",
)
async def readiness() -> JSONResponse:
    """
    Kubernetes readiness probe.
    Checks both PostgreSQL and Redis connectivity.
    Returns 200 if both are up, 503 if either is down.
    """
    db_ok = await check_db_connection()
    redis_ok = await check_redis_connection()

    overall = "ok" if (db_ok and redis_ok) else "degraded"
    http_status = status.HTTP_200_OK if overall == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE

    body = HealthResponse(
        status=overall,  # type: ignore[arg-type]
        db="ok" if db_ok else "error",
        redis="ok" if redis_ok else "error",
    )

    log.info(
        "health.readiness_check",
        db=body.db,
        redis=body.redis,
        overall=overall,
    )

    return JSONResponse(content=body.model_dump(), status_code=http_status)
