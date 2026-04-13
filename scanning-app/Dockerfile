# Talos CleanRoom Scanning Console
# Multi-stage build for smaller image
#
# Build context must be the REPO ROOT (not scanning-app/):
#   docker build -f scanning-app/Dockerfile -t scanning-console .

# --- Stage: build user-guide docs ---
FROM python:3.11-slim AS docs-builder
WORKDIR /docs
COPY docs/user-guide/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY docs/user-guide/ .
RUN mkdocs build && rm -rf site/videos/

# --- Stage: Python deps ---
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install shared library and Python dependencies together
# (single pip call ensures consistent dependency resolution)
COPY lib/talos-common /tmp/talos-common
COPY scanning-app/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install /tmp/talos-common -r requirements.txt

# Production image
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies (kubectl for Faraday/Greenbone/LOKI interactions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install kubectl (static binary — avoids apt repo signing issues)
RUN curl -fsSL "https://dl.k8s.io/release/v1.32.3/bin/linux/amd64/kubectl" -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl

# Copy Python packages from builder (to system paths, accessible by non-root user)
COPY --from=builder /install /usr/local

# Copy Alembic config and migrations
COPY scanning-app/alembic.ini .
COPY scanning-app/alembic/ ./alembic/

# Copy application files
COPY scanning-app/app/ ./app/
COPY scanning-app/static/ ./static/
COPY scanning-app/templates/ ./templates/

# Copy Vulhub K8s manifests (baked into image for kubectl apply)
COPY apps/vulhub-targets/manifests/ ./vulhub-manifests/

# Copy user guide documentation (built by docs-builder stage)
COPY --from=docs-builder /docs/site/ ./docs-site/

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/system/health || exit 1

# Start application (Alembic migrations run via init container in K8s)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
