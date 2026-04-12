# Talos CleanRoom Unified Portal
# Multi-stage build for smaller image
#
# Build context must be the REPO ROOT (not portal/):
#   docker build -f portal/Dockerfile -t portal .

FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install shared library and Python dependencies together
# (single pip call ensures consistent dependency resolution)
COPY lib/talos-common /tmp/talos-common
COPY portal/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install /tmp/talos-common -r requirements.txt

# Production image
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder (to system paths, accessible by non-root user)
COPY --from=builder /install /usr/local

# Copy application files
COPY portal/app/ ./app/
COPY portal/static/ ./static/
COPY portal/templates/ ./templates/

# Environment variables
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/system/health || exit 1

# Start application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
