"""
Main API router — mounts all sub-routers under /api/v1.
"""
from fastapi import APIRouter

from app.api.v1 import alerts, chat, health, incidents, investigations, knowledge

# Top-level router (no prefix here — prefix is applied in main.py)
api_router = APIRouter()

# Health probes are at root level (not under /api/v1) for K8s probe simplicity
# They are ALSO mounted here for documentation grouping
api_router.include_router(health.router)

# All v1 resources
v1_prefix = "/v1"

api_router.include_router(incidents.router, prefix=v1_prefix)
api_router.include_router(alerts.router, prefix=v1_prefix)
api_router.include_router(investigations.router, prefix=v1_prefix)
api_router.include_router(knowledge.router, prefix=v1_prefix)
api_router.include_router(chat.router, prefix=v1_prefix)
