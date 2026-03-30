#!/bin/bash
# Talos CleanRoom Build VM - LXC Container Setup Script
# Run this script inside the LXC container after creation
#
# Installs Docker CE, kubectl, and build utilities needed to
# build and push container images to Harbor.
#
# Usage: ./setup-lxc.sh [--repo-path /path/to/repo]

set -euo pipefail

# Ensure /usr/local/bin is in PATH
export PATH="/usr/local/bin:$PATH"

# Default values
REPO_PATH="/opt/talos-cleanroom"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --repo-path)
            REPO_PATH="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "============================================"
echo "Talos CleanRoom Build VM Setup"
echo "============================================"
echo ""

# Update system
echo "[1/5] Updating system packages..."
apt-get update && apt-get upgrade -y

# Install base dependencies
echo "[2/5] Installing base dependencies..."
apt-get install -y \
    curl \
    wget \
    gnupg \
    git \
    jq \
    ca-certificates \
    apt-transport-https \
    lsb-release

# Install Docker CE
echo "[3/5] Installing Docker CE..."
# Add Docker's official GPG key
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

# Add Docker apt repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
apt-get install -y \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin

# Configure Docker to trust Harbor with staging (Let's Encrypt) certificates
# The wildcard cert uses letsencrypt-staging by default, which is not trusted
# by Docker. This marks Harbor as an insecure registry.
# Remove this when switching to letsencrypt-prod.
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'DOCKER_EOF'
{
  "insecure-registries": ["harbor.knowledgeondemand.net"]
}
DOCKER_EOF

# Enable and restart Docker (restart required — apt install auto-starts Docker
# before daemon.json is written, so 'start' would be a no-op)
systemctl enable docker
systemctl restart docker

# Verify Docker
docker --version
echo "Docker installed and running (Harbor configured as insecure registry for staging certs)."

# Install kubectl
echo "[4/5] Installing kubectl (v1.32)..."
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.32/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.32/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list
apt-get update
apt-get install -y kubectl

# Create kubeconfig directory
mkdir -p /root/.kube

# Symlink build scripts from repository for convenience
echo "[5/5] Setting up build scripts..."
BUILD_SCRIPTS_DIR="/opt/build-scripts"
LOKI_DIR="${REPO_PATH}/apps/loki"

mkdir -p "$BUILD_SCRIPTS_DIR"

if [ -d "$LOKI_DIR" ]; then
    echo "Symlinking LOKI-RS build files..."
    for item in Dockerfile entrypoint.sh build-and-push.sh; do
        if [ -e "${LOKI_DIR}/${item}" ]; then
            rm -f "${BUILD_SCRIPTS_DIR}/${item}"
            ln -sf "${LOKI_DIR}/${item}" "${BUILD_SCRIPTS_DIR}/${item}"
        fi
    done
    echo "Build scripts linked to ${BUILD_SCRIPTS_DIR}/"
else
    echo "Warning: LOKI directory not found at ${LOKI_DIR}"
    echo "Build scripts will be available after repository is cloned."
fi

echo ""
echo "============================================"
echo "Build VM Setup Complete!"
echo "============================================"
echo ""
echo "Installed:"
echo "  - Docker CE:  $(docker --version 2>/dev/null || echo 'check manually')"
echo "  - kubectl:    $(kubectl version --client --short 2>/dev/null || echo 'check manually')"
echo "  - curl:       $(curl --version 2>/dev/null | head -1)"
echo "  - jq:         $(jq --version 2>/dev/null)"
echo ""
echo "Next Steps:"
echo ""
echo "1. Copy kubeconfig to /root/.kube/config"
echo "   (deploy-lxc.sh handles this automatically)"
echo ""
echo "2. Build and push the LOKI-RS image to Harbor:"
echo "   cd ${LOKI_DIR}"
echo "   ./build-and-push.sh"
echo ""
echo "   Or use the convenience symlink:"
echo "   cd ${BUILD_SCRIPTS_DIR}"
echo "   ./build-and-push.sh"
echo ""
echo "============================================"
