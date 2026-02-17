#!/bin/bash
# Talos CleanRoom Deployment Web UI - LXC Container Setup Script
# Run this script inside the LXC container after creation
#
# Usage: ./setup-lxc.sh [--repo-path /path/to/repo] [--webui-password admin]

set -euo pipefail

# Ensure /usr/local/bin is in PATH
export PATH="/usr/local/bin:$PATH"

# Default values
REPO_PATH="/opt/talos-cleanroom"
WEBUI_USER="admin"
WEBUI_PASSWORD="admin"
WEBUI_PORT="8000"
APP_DIR="/opt/deployment-webui"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --repo-path)
            REPO_PATH="$2"
            shift 2
            ;;
        --webui-password)
            WEBUI_PASSWORD="$2"
            shift 2
            ;;
        --webui-port)
            WEBUI_PORT="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "============================================"
echo "Talos CleanRoom Deployment Web UI Setup"
echo "============================================"
echo ""

# Update system
echo "[1/10] Updating system packages..."
apt-get update && apt-get upgrade -y

# Install base dependencies
echo "[2/10] Installing base dependencies..."
apt-get install -y \
    curl \
    wget \
    gnupg \
    git \
    jq \
    unzip \
    ca-certificates \
    python3 \
    python3-pip \
    python3-venv \
    apt-transport-https \
    lsb-release

# Install kubectl
echo "[3/10] Installing kubectl..."
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list
apt-get update
apt-get install -y kubectl

# Install Helm
echo "[4/10] Installing Helm..."
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version --short

# Install Terraform
echo "[5/10] Installing Terraform..."
TERRAFORM_VERSION="1.7.0"
curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" -o /tmp/terraform.zip
unzip -o /tmp/terraform.zip -d /usr/local/bin/
rm /tmp/terraform.zip
terraform version

# Install talosctl
echo "[6/10] Installing talosctl..."
curl -fsSL https://github.com/siderolabs/talos/releases/latest/download/talosctl-linux-amd64 -o /usr/local/bin/talosctl
chmod +x /usr/local/bin/talosctl
talosctl version --client

# Install talhelper
echo "[7/10] Installing talhelper..."
curl -fsSL https://github.com/budimanjojo/talhelper/releases/latest/download/talhelper_linux_amd64.tar.gz -o /tmp/talhelper.tar.gz
tar -xzf /tmp/talhelper.tar.gz -C /usr/local/bin/
rm /tmp/talhelper.tar.gz
talhelper --version

# Install SOPS
echo "[8/10] Installing SOPS..."
SOPS_VERSION="3.8.1"
curl -fsSL "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.amd64" -o /usr/local/bin/sops
chmod +x /usr/local/bin/sops
sops --version

# Clone or setup repository
echo "[9/10] Setting up repository..."
if [ ! -d "$REPO_PATH" ]; then
    echo "Repository not found at $REPO_PATH"
    echo "You will need to clone the repository or create a bind mount."
    mkdir -p "$REPO_PATH"
fi

# Setup application directory
mkdir -p "$APP_DIR"

# Copy web UI files if repository exists
if [ -d "$REPO_PATH/deployment-webui" ]; then
    echo "Copying web UI files from repository..."
    cp -r "$REPO_PATH/deployment-webui/app" "$APP_DIR/"
    cp -r "$REPO_PATH/deployment-webui/static" "$APP_DIR/"
    cp -r "$REPO_PATH/deployment-webui/templates" "$APP_DIR/"
    cp "$REPO_PATH/deployment-webui/requirements.txt" "$APP_DIR/"
fi

# Create Python virtual environment and install dependencies
echo "[10/10] Setting up Python environment..."
cd "$APP_DIR"
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

pip install --upgrade pip

if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    echo "Warning: requirements.txt not found. Installing dependencies manually..."
    pip install \
        fastapi==0.109.0 \
        uvicorn[standard]==0.27.0 \
        python-jose[cryptography]==3.3.0 \
        passlib==1.7.4 \
        bcrypt==4.0.1 \
        python-multipart==0.0.6 \
        pydantic==2.5.3 \
        pydantic-settings==2.1.0 \
        pyyaml==6.0.1 \
        jinja2==3.1.3 \
        aiofiles==23.2.1 \
        websockets==12.0 \
        python-hcl2==4.3.2
fi

# Generate password hash (venv is active, so python3 has passlib)
echo ""
echo "Generating password hash for web UI..."
PASSWORD_HASH=$(python3 -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('$WEBUI_PASSWORD'))")

# Deactivate virtual environment
deactivate

# Generate secret key
SECRET_KEY=$(openssl rand -hex 32)

# Create environment file
echo "Creating environment file..."
cat > "$APP_DIR/.env" << EOF
# Talos CleanRoom Deployment Web UI Configuration
# Generated by setup-lxc.sh on $(date)

# Authentication
ADMIN_USERNAME=$WEBUI_USER
ADMIN_PASSWORD_HASH=$PASSWORD_HASH
SECRET_KEY=$SECRET_KEY
ACCESS_TOKEN_EXPIRE_HOURS=8

# Repository
REPO_ROOT=$REPO_PATH

# Deployment Settings
MASTER_NODE=talos-CleanRoom-master-01.knowledgeondemand.net
HEALTH_CHECK_RETRIES=30
HEALTH_CHECK_INTERVAL=10
EOF

chmod 600 "$APP_DIR/.env"

# Create systemd service
echo "Creating systemd service..."
cat > /etc/systemd/system/deployment-webui.service << EOF
[Unit]
Description=Talos CleanRoom Deployment Web UI
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $WEBUI_PORT
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable service
systemctl daemon-reload
systemctl enable deployment-webui.service

# Create kubeconfig directory
mkdir -p /root/.kube

# Create SOPS keys directory
mkdir -p /root/.config/sops/age

echo ""
echo "============================================"
echo "Setup Complete!"
echo "============================================"
echo ""
echo "Next Steps:"
echo ""
echo "1. If using bind mount for repository, add to /etc/pve/lxc/<VMID>.conf:"
echo "   mp0: /path/to/talos-cleanroom,mp=$REPO_PATH"
echo ""
echo "2. Copy SOPS age keys to: /root/.config/sops/age/keys.txt"
echo ""
echo "3. Start the web UI service:"
echo "   systemctl start deployment-webui"
echo ""
echo "4. Access the web UI at: http://<container-ip>:$WEBUI_PORT"
echo ""
echo "5. Login credentials:"
echo "   Username: $WEBUI_USER"
echo "   Password: $WEBUI_PASSWORD"
echo ""
echo "Service commands:"
echo "   systemctl status deployment-webui"
echo "   systemctl start deployment-webui"
echo "   systemctl stop deployment-webui"
echo "   journalctl -u deployment-webui -f"
echo ""
echo "============================================"
