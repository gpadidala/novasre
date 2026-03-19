"""
NovaSRE Database — Async SQLAlchemy engine and session management.
Uses asyncpg driver with connection pooling.
"""
from collections.abc import AsyncGenerator
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,
    pool_pre_ping=True,          # Verify connections before checkout
    pool_size=20,                # Persistent connections in pool
    max_overflow=10,             # Extra connections allowed above pool_size
    pool_recycle=3600,           # Recycle connections every hour
    pool_timeout=30,             # Wait at most 30s for a free connection
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=True,
    autocommit=False,
)

# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Health / connectivity check
# ---------------------------------------------------------------------------


async def check_db_connection() -> bool:
    """
    Check if the database is reachable.
    Returns True on success, False on any failure.
    Used by the health endpoint and startup lifespan.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        log.info("database.connection_ok")
        return True
    except Exception as exc:
        log.error("database.connection_failed", error=str(exc))
        return False


# ---------------------------------------------------------------------------
# Table creation (for testing / dev without Alembic)
# ---------------------------------------------------------------------------


async def create_all_tables() -> None:
    """Create all tables defined in SQLAlchemy metadata. Dev/test only."""
    from app.models.base import Base  # noqa: F401 — triggers model registration

    # Import all models so their metadata is registered
    import app.models.alert  # noqa: F401
    import app.models.incident  # noqa: F401
    import app.models.investigation  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.service  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("database.tables_created")


async def drop_all_tables() -> None:
    """Drop all tables. Dev/test only."""
    from app.models.base import Base  # noqa: F401

    import app.models.alert  # noqa: F401
    import app.models.incident  # noqa: F401
    import app.models.investigation  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.service  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    log.info("database.tables_dropped")
