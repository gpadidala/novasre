# NovaSRE Backend — Multi-stage Dockerfile
# Stage 1: Build dependencies
# Stage 2: Production runtime

# ============================================================
# Stage 1 — Builder
# ============================================================
FROM python:3.11-slim AS builder

# System dependencies for compiled packages (asyncpg, Prophet, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    libpq-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip + install build tools
RUN pip install --upgrade pip setuptools wheel hatchling

# Copy dependency spec first (layer caching)
WORKDIR /build
COPY pyproject.toml ./

# Install production dependencies only
RUN pip install --no-cache-dir \
    fastapi>=0.115.0 \
    uvicorn[standard]>=0.30.0 \
    langgraph>=0.2.0 \
    langchain>=0.3.0 \
    langchain-openai>=0.2.0 \
    openai>=1.50.0 \
    pydantic>=2.0.0 \
    pydantic-settings>=2.0.0 \
    sqlalchemy>=2.0.0 \
    asyncpg>=0.29.0 \
    aiosqlite>=0.20.0 \
    alembic>=1.13.0 \
    redis>=5.0.0 \
    aioredis>=2.0.0 \
    httpx>=0.27.0 \
    structlog>=24.0.0 \
    prometheus-client>=0.20.0 \
    celery>=5.4.0 \
    scikit-learn>=1.5.0 \
    pandas>=2.0.0 \
    numpy>=1.26.0 \
    python-multipart>=0.0.9 \
    greenlet>=3.0.0

# Prophet has large dependencies — install separately for better caching
RUN pip install --no-cache-dir prophet>=1.1.5 || \
    echo "Prophet install failed — will use stub. Check pystan/cmdstanpy availability."

# ChromaDB
RUN pip install --no-cache-dir chromadb>=0.5.0 || \
    echo "ChromaDB install failed — vector store unavailable."

# ============================================================
# Stage 2 — Runtime
# ============================================================
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="NovaSRE Backend"
LABEL org.opencontainers.image.description="AI-powered SRE platform backend"
LABEL org.opencontainers.image.version="0.1.0"

# Runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user
RUN groupadd --gid 1001 novasre && \
    useradd --uid 1001 --gid novasre --shell /bin/bash --create-home novasre

# Application directory
WORKDIR /app

# Copy application code
COPY --chown=novasre:novasre . .

# Switch to non-root user
USER novasre

# Environment defaults (overridden by docker-compose / K8s)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    APP_ENV=production \
    LOG_LEVEL=INFO

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1


# Expose application port
EXPOSE 8000

# Default command — override in docker-compose for dev (--reload)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--log-config", "/dev/null"]
