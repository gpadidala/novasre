"""
NovaSRE FastAPI dependencies — injected into route handlers via Depends().
"""
from collections.abc import AsyncGenerator
from typing import Annotated

import redis.asyncio as aioredis
import structlog
from fastapi import Depends

from app.config import Settings, get_settings
from app.database import AsyncSessionLocal, get_db

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Settings dependency
# ---------------------------------------------------------------------------


def get_settings_dep() -> Settings:
    """Inject application settings."""
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]

# ---------------------------------------------------------------------------
# Redis dependency
# ---------------------------------------------------------------------------

_redis_pool: aioredis.Redis | None = None


async def get_redis_client() -> aioredis.Redis:
    """
    Return a module-level Redis client (connection pool shared across requests).
    Initialised lazily on first call.
    """
    global _redis_pool
    if _redis_pool is None:
        settings = get_settings()
        _redis_pool = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
        )
    return _redis_pool


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI dependency: yields a Redis client."""
    client = await get_redis_client()
    try:
        yield client
    except Exception:
        raise


async def check_redis_connection() -> bool:
    """
    Check if Redis is reachable.
    Returns True on success, False on any failure.
    """
    try:
        client = await get_redis_client()
        await client.ping()
        log.info("redis.connection_ok")
        return True
    except Exception as exc:
        log.error("redis.connection_failed", error=str(exc))
        return False


async def close_redis() -> None:
    """Close the Redis connection pool on shutdown."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None
        log.info("redis.pool_closed")


# ---------------------------------------------------------------------------
# Typed aliases for common dependencies
# ---------------------------------------------------------------------------
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]
