#!/bin/bash
# Talos CleanRoom Deployment Web UI - LXC Deployment Script
# Deploys the web UI as an LXC container on Proxmox
#
# Usage: ./deploy-lxc.sh

set -eo pipefail

# Disable bash history expansion to handle '!' in API tokens (e.g., user@pam!tokenid=secret)
set +H

# Configuration - Edit these values
PROXMOX_HOST="pve01.knowledgeondemand.net"
PROXMOX_API_URL="https://${PROXMOX_HOST}:8006"

# LXC Container Settings
LXC_VMID=200
LXC_HOSTNAME="deployment-webui"
LXC_IP="10.83.3.190/24"          # Adjust to your network
LXC_GATEWAY="10.83.3.1"          # Adjust to your gateway
LXC_CORES=2
LXC_MEMORY=2048
LXC_DISK=20
LXC_STORAGE="local-lvm"
NETWORK_BRIDGE="vmbr0"
VLAN_ID=3                        # Set to 0 for no VLAN

# DNS Settings
DNS_DOMAIN="knowledgeondemand.net"
DNS_SERVERS='["8.8.8.8", "8.8.4.4"]'

# Web UI Settings
WEBUI_USER="admin"
WEBUI_PASSWORD="admin"           # Change this!

# SSH User Settings (non-root user for SSH access)
SSH_USER="deploy"                # Non-root user for SSH access
SSH_USER_GROUPS="sudo"           # Groups for the SSH user

# GitHub SSH Settings (for private repository access)
GITHUB_SSH_KEY=""                # Path to SSH private key for GitHub
GITHUB_REPO_URL="git@github.com:williamdemarigny/Talos-CleanRoom.git"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}"
echo "============================================"
echo "Talos CleanRoom Deployment Web UI"
echo "LXC Container Deployment"
echo "============================================"
echo -e "${NC}"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="${SCRIPT_DIR}/terraform"

# Check for terraform
if ! command -v terraform &> /dev/null; then
    echo -e "${RED}Error: terraform is not installed${NC}"
    exit 1
fi

# ===========================================
# COLLECT ALL CREDENTIALS UPFRONT
# ===========================================

echo -e "${YELLOW}Please provide the following credentials:${NC}"
echo ""

if [ -z "$PROXMOX_API_TOKEN" ]; then
    echo -e "${YELLOW}Proxmox API Token (format: user@pam!tokenid=secret):${NC}"
    read -r PROXMOX_API_TOKEN
fi

if [ -z "$PROXMOX_SSH_PASSWORD" ]; then
    echo -e "${YELLOW}Proxmox SSH password for root:${NC}"
    read -rs PROXMOX_SSH_PASSWORD
    echo ""
fi

if [ -z "$LXC_ROOT_PASSWORD" ]; then
    echo -e "${YELLOW}Password for LXC container root user:${NC}"
    read -rs LXC_ROOT_PASSWORD
    echo ""
fi

if [ -z "$SSH_USER_PASSWORD" ]; then
    echo -e "${YELLOW}Password for deploy user '${SSH_USER}' (used for SSH to container):${NC}"
    read -rs SSH_USER_PASSWORD
    echo ""
fi

# Prompt for GitHub SSH key
if [ -z "$GITHUB_SSH_KEY" ]; then
    # Check common SSH key locations
    DEFAULT_KEY=""
    for key_path in ~/.ssh/id_ed25519 ~/.ssh/id_rsa ~/.ssh/github ~/.ssh/id_ecdsa; do
        if [ -f "$key_path" ]; then
            DEFAULT_KEY="$key_path"
            break
        fi
    done

    if [ -n "$DEFAULT_KEY" ]; then
        echo -e "${YELLOW}Path to GitHub SSH private key [${DEFAULT_KEY}]:${NC}"
        read -r GITHUB_SSH_KEY
        GITHUB_SSH_KEY="${GITHUB_SSH_KEY:-$DEFAULT_KEY}"
    else
        echo -e "${YELLOW}Path to GitHub SSH private key:${NC}"
        read -r GITHUB_SSH_KEY
    fi
fi

# Validate SSH key exists
if [ ! -f "$GITHUB_SSH_KEY" ]; then
    echo -e "${RED}Error: SSH key not found at ${GITHUB_SSH_KEY}${NC}"
    exit 1
fi

echo -e "${GREEN}Using SSH key: ${GITHUB_SSH_KEY}${NC}"

# ===========================================
# SSH SETUP
# ===========================================

SSH_OPTS="-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null -o ConnectTimeout=30"

# Check if sshpass is available (optional - enables automation)
SSHPASS_AVAILABLE=false
if command -v sshpass &> /dev/null; then
    SSHPASS_AVAILABLE=true
    echo -e "${GREEN}sshpass found - SSH will be automated${NC}"
else
    echo -e "${YELLOW}sshpass not found - you will be prompted for passwords${NC}"
    echo -e "${YELLOW}(Install sshpass to automate: choco install sshpass)${NC}"
fi

# Helper: SSH to Proxmox (uses sshpass if available)
proxmox_ssh() {
    if [ "$SSHPASS_AVAILABLE" = true ]; then
        sshpass -p "${PROXMOX_SSH_PASSWORD}" ssh ${SSH_OPTS} root@${PROXMOX_HOST} "$@"
    else
        ssh ${SSH_OPTS} root@${PROXMOX_HOST} "$@"
    fi
}

# Helper: Run command in container via pct exec
pct_exec() {
    proxmox_ssh "pct exec ${LXC_VMID} -- $1"
}

# ===========================================
# CHECK LXC TEMPLATE
# ===========================================

echo -e "${GREEN}[1/5] Checking LXC template on Proxmox...${NC}"
echo -e "${YELLOW}  (You may be prompted for Proxmox password once)${NC}"

TEMPLATE_NAME="debian-12-standard_12.12-1_amd64.tar.zst"
TEMPLATE_STORAGE="cephfs"

# Check and download template in one SSH session
proxmox_ssh << TEMPLATE_CHECK
TEMPLATE_EXISTS=\$(pveam list ${TEMPLATE_STORAGE} 2>/dev/null | grep -c '${TEMPLATE_NAME}' || echo "0")
if [ "\$TEMPLATE_EXISTS" = "0" ]; then
    echo "  Template not found. Downloading..."
    pveam download ${TEMPLATE_STORAGE} ${TEMPLATE_NAME} || {
        echo "  Failed to download template."
        echo "  Please download manually: pveam download ${TEMPLATE_STORAGE} ${TEMPLATE_NAME}"
        exit 1
    }
else
    echo "  Template exists"
fi
TEMPLATE_CHECK

echo -e "${GREEN}  Template check complete${NC}"

# ===========================================
# CREATE TERRAFORM CONFIG
# ===========================================

echo -e "${GREEN}[2/5] Creating Terraform configuration...${NC}"

cat > "${TERRAFORM_DIR}/terraform.tfvars" << EOF
# Auto-generated by deploy-lxc.sh on $(date)

# Proxmox Connection
proxmox_api_url      = "${PROXMOX_API_URL}"
proxmox_api_token    = "${PROXMOX_API_TOKEN}"
proxmox_ssh_user     = "root"
proxmox_ssh_password = "${PROXMOX_SSH_PASSWORD}"
proxmox_node         = ""
proxmox_pool         = ""

# LXC Container Configuration
lxc_vmid      = ${LXC_VMID}
lxc_hostname  = "${LXC_HOSTNAME}"
lxc_cores     = ${LXC_CORES}
lxc_memory    = ${LXC_MEMORY}
lxc_swap      = 512
lxc_disk_size = ${LXC_DISK}
lxc_storage   = "${LXC_STORAGE}"
lxc_tags      = ["deployment", "webui", "management"]

# Template
template_storage      = "${TEMPLATE_STORAGE}"
lxc_template_filename = "${TEMPLATE_NAME}"

# Network
network_bridge  = "${NETWORK_BRIDGE}"
vlan_id         = ${VLAN_ID}
lxc_ip_address  = "${LXC_IP}"
lxc_gateway     = "${LXC_GATEWAY}"
lxc_mac_address = ""

# DNS
dns_domain  = "${DNS_DOMAIN}"
dns_servers = ${DNS_SERVERS}

# Auth
lxc_root_password = "${LXC_ROOT_PASSWORD}"
ssh_public_keys   = []

# SSH User (created via pct exec after deployment)
ssh_user          = "${SSH_USER}"
ssh_user_password = "${SSH_USER_PASSWORD}"
ssh_user_groups   = "${SSH_USER_GROUPS}"

# Web UI
webui_admin_username = "${WEBUI_USER}"
webui_admin_password = "${WEBUI_PASSWORD}"
EOF

echo "  Config written to ${TERRAFORM_DIR}/terraform.tfvars"

# ===========================================
# TERRAFORM DEPLOY
# ===========================================

echo -e "${GREEN}[3/5] Running Terraform...${NC}"
cd "${TERRAFORM_DIR}"
terraform init
terraform plan -out=.tfplan

echo ""
echo -e "${YELLOW}Deploy LXC container?${NC}"
echo "  Host: ${PROXMOX_HOST}"
echo "  VMID: ${LXC_VMID}"
echo "  IP:   ${LXC_IP}"
read -p "Proceed? (y/n) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

terraform apply .tfplan

CONTAINER_IP="${LXC_IP%/*}"

echo -e "${GREEN}Container deployed at ${CONTAINER_IP}${NC}"

# ===========================================
# BOOTSTRAP VIA PCT EXEC
# Create deploy user, install SSH, copy keys
# All done in ONE SSH session to avoid multiple password prompts
# ===========================================

echo -e "${GREEN}[4/5] Bootstrapping container via pct exec...${NC}"
echo -e "${YELLOW}  (One Proxmox password prompt for entire bootstrap)${NC}"

# Prepare base64-encoded data
PASS_B64=$(echo -n "${SSH_USER}:${SSH_USER_PASSWORD}" | base64)
SUDOERS_B64=$(echo -n "${SSH_USER} ALL=(ALL) NOPASSWD:ALL" | base64)
GITHUB_KEY_B64=$(base64 -w0 < "${GITHUB_SSH_KEY}")
SSH_CONFIG_B64=$(echo -n "Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/github_deploy_key
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new" | base64)

# Run entire bootstrap in ONE SSH session to Proxmox
proxmox_ssh << BOOTSTRAP_SCRIPT
set -e

# Wait for container
echo "  Waiting for container..."
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if pct status ${LXC_VMID} 2>/dev/null | grep -q running; then
        echo "  Container is running"
        break
    fi
    sleep 5
done

echo "  Installing packages..."
pct exec ${LXC_VMID} -- apt-get update
pct exec ${LXC_VMID} -- apt-get install -y sudo git openssh-server locales curl wget gnupg ca-certificates

echo "  Configuring locale..."
pct exec ${LXC_VMID} -- sed -i 's/# en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen
pct exec ${LXC_VMID} -- locale-gen en_US.UTF-8

echo "  Creating user: ${SSH_USER}..."
pct exec ${LXC_VMID} -- useradd -m -s /bin/bash -G ${SSH_USER_GROUPS} ${SSH_USER} 2>/dev/null || true
pct exec ${LXC_VMID} -- bash -c 'echo ${PASS_B64} | base64 -d | chpasswd'
pct exec ${LXC_VMID} -- bash -c 'echo ${SUDOERS_B64} | base64 -d > /etc/sudoers.d/${SSH_USER}'
pct exec ${LXC_VMID} -- chmod 440 /etc/sudoers.d/${SSH_USER}

echo "  Setting up SSH..."
pct exec ${LXC_VMID} -- mkdir -p /home/${SSH_USER}/.ssh
pct exec ${LXC_VMID} -- chmod 700 /home/${SSH_USER}/.ssh

echo "  Copying GitHub SSH key..."
pct exec ${LXC_VMID} -- bash -c 'echo ${GITHUB_KEY_B64} | base64 -d > /home/${SSH_USER}/.ssh/github_deploy_key'
pct exec ${LXC_VMID} -- chmod 600 /home/${SSH_USER}/.ssh/github_deploy_key

echo "  Creating SSH config..."
pct exec ${LXC_VMID} -- bash -c 'echo ${SSH_CONFIG_B64} | base64 -d > /home/${SSH_USER}/.ssh/config'
pct exec ${LXC_VMID} -- chmod 600 /home/${SSH_USER}/.ssh/config

echo "  Adding GitHub to known_hosts..."
pct exec ${LXC_VMID} -- bash -c 'ssh-keyscan -t ed25519,rsa github.com >> /home/${SSH_USER}/.ssh/known_hosts 2>/dev/null'
pct exec ${LXC_VMID} -- chmod 600 /home/${SSH_USER}/.ssh/known_hosts

pct exec ${LXC_VMID} -- chown -R ${SSH_USER}:${SSH_USER} /home/${SSH_USER}/.ssh

echo "  Starting SSH service..."
pct exec ${LXC_VMID} -- sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
pct exec ${LXC_VMID} -- systemctl enable ssh
pct exec ${LXC_VMID} -- systemctl start ssh

echo "  Bootstrap complete!"
BOOTSTRAP_SCRIPT

echo -e "${GREEN}  Bootstrap complete - deploy user created${NC}"

# ===========================================
# FINISH SETUP VIA SSH AS DEPLOY USER
# Use SSH multiplexing to reuse single connection
# ===========================================

echo -e "${GREEN}[5/5] Completing setup via SSH as ${SSH_USER}...${NC}"

# Clear old host keys
ssh-keygen -R "${CONTAINER_IP}" 2>/dev/null || true

# Setup SSH multiplexing (reuse single connection, password only entered once)
CONTROL_PATH="/tmp/ssh-deploy-${LXC_VMID}"
SSH_MUX_OPTS="${SSH_OPTS} -o ControlMaster=auto -o ControlPath=${CONTROL_PATH} -o ControlPersist=300"

# Helper: SSH to container (uses sshpass if available, otherwise prompts once)
container_ssh() {
    if [ "$SSHPASS_AVAILABLE" = true ]; then
        sshpass -p "${SSH_USER_PASSWORD}" ssh ${SSH_MUX_OPTS} ${SSH_USER}@${CONTAINER_IP} "$@"
    else
        ssh ${SSH_MUX_OPTS} ${SSH_USER}@${CONTAINER_IP} "$@"
    fi
}

# Wait for SSH and establish master connection
echo "  Waiting for SSH..."
if [ "$SSHPASS_AVAILABLE" = false ]; then
    echo -e "${YELLOW}  Enter the deploy user password when prompted (only once due to multiplexing)${NC}"
fi

for i in {1..6}; do
    if container_ssh "echo ok" 2>/dev/null | grep -q ok; then
        echo -e "${GREEN}  SSH connected${NC}"
        break
    fi
    sleep 5
done

# Cleanup function for SSH multiplexing
cleanup_ssh() {
    ssh -O exit -o ControlPath=${CONTROL_PATH} ${SSH_USER}@${CONTAINER_IP} 2>/dev/null || true
}
trap cleanup_ssh EXIT

# Run the rest via multiplexed SSH (no more password prompts)
ssh ${SSH_MUX_OPTS} ${SSH_USER}@${CONTAINER_IP} << REMOTE_SETUP
set -e
export PATH="/usr/local/bin:\$PATH"
export LANG=en_US.UTF-8

echo "=== Testing GitHub connectivity ==="
ssh -T git@github.com 2>&1 || true

echo "=== Cloning repository ==="
sudo mkdir -p /opt/Talos-CleanRoom
sudo chown ${SSH_USER}:${SSH_USER} /opt/Talos-CleanRoom
git clone ${GITHUB_REPO_URL} /opt/Talos-CleanRoom

echo "=== Running setup script ==="
cd /opt/Talos-CleanRoom/deployment-webui/scripts
chmod +x setup-lxc.sh
sudo ./setup-lxc.sh --webui-password "${WEBUI_PASSWORD}"

echo "=== Starting web UI service ==="
sudo systemctl start deployment-webui || echo "Service may need manual start"
sudo systemctl status deployment-webui --no-pager || true

echo "=== Disabling root SSH login ==="
sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
REMOTE_SETUP

# ===========================================
# DONE
# ===========================================

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}Setup Complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Web UI: http://${CONTAINER_IP}:8000"
echo "Login:  ${WEBUI_USER} / ${WEBUI_PASSWORD}"
echo ""
echo "SSH access:"
echo "  ssh ${SSH_USER}@${CONTAINER_IP}"
echo ""
echo "Don't forget to copy SOPS keys:"
echo "  ssh ${SSH_USER}@${CONTAINER_IP} 'mkdir -p ~/.config/sops/age'"
echo "  scp ~/.config/sops/age/keys.txt ${SSH_USER}@${CONTAINER_IP}:~/.config/sops/age/"
echo ""
echo -e "${YELLOW}Recovery (if locked out):${NC}"
echo "  ssh root@${PROXMOX_HOST} 'pct exec ${LXC_VMID} -- bash'"
echo ""
