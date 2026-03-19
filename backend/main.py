"""
NovaSRE Backend — FastAPI application entry point.

Start with:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
import sys
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings

# ---------------------------------------------------------------------------
# Structured logging setup (must happen before any imports that log)
# ---------------------------------------------------------------------------


def _configure_logging() -> None:
    import logging

    import structlog

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if settings.is_development
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configure_logging()
log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.
    - Startup: verify DB + Redis connectivity, run pending migrations check
    - Shutdown: close connection pools cleanly
    """
    # === STARTUP ===
    log.info("novasre.starting", env=settings.app_env, version="0.1.0")

    # Test database connectivity
    from app.database import check_db_connection

    db_ok = await check_db_connection()
    if not db_ok:
        log.warning(
            "novasre.db_unavailable",
            message="PostgreSQL not reachable on startup — check DATABASE_URL",
        )
    else:
        log.info("novasre.db_connected")

    # Test Redis connectivity
    from app.dependencies import check_redis_connection

    redis_ok = await check_redis_connection()
    if not redis_ok:
        log.warning(
            "novasre.redis_unavailable",
            message="Redis not reachable on startup — check REDIS_URL",
        )
    else:
        log.info("novasre.redis_connected")

    log.info(
        "novasre.started",
        db="ok" if db_ok else "degraded",
        redis="ok" if redis_ok else "degraded",
    )

    yield  # Application runs here

    # === SHUTDOWN ===
    log.info("novasre.shutting_down")

    from app.dependencies import close_redis
    from app.database import engine

    await close_redis()
    await engine.dispose()

    log.info("novasre.stopped")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="NovaSRE",
    description=(
        "Next-generation AI-powered SRE platform. "
        "Unifies Grafana, Mimir, Loki, Tempo, Pyroscope, and Faro into a single "
        "intelligent investigation agent."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# API router
# ---------------------------------------------------------------------------

from app.api.router import api_router  # noqa: E402

app.include_router(api_router, prefix="/api")

# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

from app.api.websocket import agent_websocket_handler  # noqa: E402


@app.websocket("/ws/agent/{session_id}")
async def agent_websocket(websocket: WebSocket, session_id: str) -> None:
    """
    Real-time bidirectional WebSocket for the NovaSRE agent.

    Client sends:
      { "type": "message", "payload": { "content": "...", "incident_id": "..." } }
      { "type": "ping" }

    Server streams:
      thinking → tool_call → tool_result → finding → rca → done
    """
    await agent_websocket_handler(websocket, session_id)


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception) -> JSONResponse:
    log.error(
        "novasre.unhandled_exception",
        path=str(request.url),
        method=request.method,
        error=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": str(exc) if settings.is_development else "An unexpected error occurred",
        },
    )


# ---------------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "service": "NovaSRE",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/api/health",
        "ready": "/api/health/ready",
        "ws": "/ws/agent/{session_id}",
    }
