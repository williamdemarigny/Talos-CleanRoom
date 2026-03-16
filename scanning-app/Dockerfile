# Talos CleanRoom Scanning Console
# Multi-stage build for smaller image
#
# Build context must be the REPO ROOT (not scanning-app/):
#   docker build -f scanning-app/Dockerfile -t scanning-console .

FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install shared library first (separate layer for caching)
COPY lib/talos-common /tmp/talos-common
RUN pip install --no-cache-dir --user /tmp/talos-common

# Install Python dependencies
COPY scanning-app/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Production image
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies (kubectl for Faraday/Greenbone/LOKI interactions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install kubectl
RUN curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg \
    && echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list \
    && apt-get update \
    && apt-get install -y kubectl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy Alembic config and migrations
COPY scanning-app/alembic.ini .
COPY scanning-app/alembic/ ./alembic/

# Copy application files
COPY scanning-app/app/ ./app/
COPY scanning-app/static/ ./static/
COPY scanning-app/templates/ ./templates/

# Environment variables
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/system/health || exit 1

# Start application (Alembic migrations run via init container in K8s)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
