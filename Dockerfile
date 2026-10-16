# ==============================================================================
# Multi-Stage Dockerfile for DQ Scoring API / import worker (no PySpark, no Java)
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build & Dependencies
# ------------------------------------------------------------------------------
FROM python:3.13-slim-trixie AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install locked runtime dependencies (no dev/compute groups: PySpark ships only in Dockerfile.spark)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project && uv cache clean

# Copy application source and install package
COPY src/ ./src/
COPY README.md ./
RUN uv sync --frozen --no-dev && uv cache clean

# ------------------------------------------------------------------------------
# Stage 2: Runtime Environment
# ------------------------------------------------------------------------------
FROM python:3.13-slim-trixie AS runner

# curl for health probes
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Non-root secure user (UID 10001) per Chapter 4 Security standards
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser && \
    mkdir -p /opt/dq/scratch /opt/dq/security && \
    chown -R appuser:appgroup /opt/dq

WORKDIR /app

# Copy virtual environment and source
COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --chown=appuser:appgroup src/ /app/src/
COPY --chown=appuser:appgroup pyproject.toml /app/

USER appuser

EXPOSE 8000
# Note: Workload healthchecks are defined by orchestrator probes (K8s liveness/readiness
# or compose healthcheck) to avoid marking worker/importer non-HTTP workloads unhealthy.
CMD ["uvicorn", "dq_scoring.presentation.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
