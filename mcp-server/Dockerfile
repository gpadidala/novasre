# ============================================================
# NovaSRE MCP Server — Dockerfile
# ============================================================
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Builder stage — install Python deps
# ---------------------------------------------------------------------------
FROM base AS builder

COPY pyproject.toml ./
COPY tools/ ./tools/
COPY server.py ./
RUN pip install --no-cache-dir .

# ---------------------------------------------------------------------------
# Production stage
# ---------------------------------------------------------------------------
FROM base AS production

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Create non-root user
RUN groupadd -r novasre && useradd -r -g novasre novasre && \
    chown -R novasre:novasre /app

USER novasre

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Default: run as HTTP server on :8001
# Override CMD to "python server.py" for stdio transport
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
