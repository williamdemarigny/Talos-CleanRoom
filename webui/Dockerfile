# Talos CleanRoom Deployment Web UI
# Multi-stage build for smaller image
#
# Build context must be the REPO ROOT (not webui/):
#   docker build -f webui/Dockerfile -t deployment-webui .

FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install shared library and Python dependencies together
# (single pip call ensures consistent dependency resolution)
COPY lib/talos-common /tmp/talos-common
COPY webui/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install /tmp/talos-common -r requirements.txt

# Production image
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies and deployment tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    git \
    jq \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install kubectl
RUN curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg \
    && echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list \
    && apt-get update \
    && apt-get install -y kubectl \
    && rm -rf /var/lib/apt/lists/*

# Install Helm
RUN curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Install Terraform
RUN curl -fsSL https://releases.hashicorp.com/terraform/1.7.0/terraform_1.7.0_linux_amd64.zip -o terraform.zip \
    && unzip terraform.zip \
    && mv terraform /usr/local/bin/ \
    && rm terraform.zip

# Install talosctl
RUN curl -fsSL https://github.com/siderolabs/talos/releases/latest/download/talosctl-linux-amd64 -o /usr/local/bin/talosctl \
    && chmod +x /usr/local/bin/talosctl

# Install talhelper
RUN curl -fsSL https://github.com/budimanjojo/talhelper/releases/latest/download/talhelper_linux_amd64.tar.gz -o talhelper.tar.gz \
    && tar -xzf talhelper.tar.gz \
    && mv talhelper /usr/local/bin/ \
    && rm talhelper.tar.gz

# Install sops
RUN curl -fsSL https://github.com/getsops/sops/releases/latest/download/sops-v3.8.1.linux.amd64 -o /usr/local/bin/sops \
    && chmod +x /usr/local/bin/sops

# Copy Python packages from builder (to system paths for consistency)
COPY --from=builder /install /usr/local

# Copy application files
COPY webui/app/ ./app/
COPY webui/static/ ./static/
COPY webui/templates/ ./templates/

# Create mount point for repository
VOLUME ["/repo"]

# Create persistent data directory for credential state
RUN mkdir -p /app/data

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV REPO_ROOT=/repo

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/system/health || exit 1

# Start application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
