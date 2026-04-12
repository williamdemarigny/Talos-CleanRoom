#!/bin/bash
# Talos CleanRoom Deployment Web UI - LXC Deployment Script
# Deploys the web UI as an LXC container on Proxmox
#
# Usage: ./deploy-lxc.sh

set -euo pipefail

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
GIT_BRANCH="refactor/restructure"                   # Branch to clone

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="${SCRIPT_DIR}/../terraform/webui-lxc"

# Source shared LXC deploy functions
source "${SCRIPT_DIR}/../lib/lxc-deploy-common.sh"

echo -e "${GREEN}"
echo "============================================"
echo "Talos CleanRoom Deployment Web UI"
echo "LXC Container Deployment"
echo "============================================"
echo -e "${NC}"

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

prompt_credential PROXMOX_API_TOKEN "Proxmox API Token (format: user@pam!tokenid=secret)" false
prompt_credential PROXMOX_SSH_PASSWORD "Proxmox SSH password for root" true
prompt_credential LXC_ROOT_PASSWORD "Password for LXC container root user" true
prompt_credential SSH_USER_PASSWORD "Password for deploy user '${SSH_USER}' (used for SSH to container)" true

# Resolve and validate GitHub SSH key
resolve_ssh_key "" || exit 1

# ===========================================
# VALIDATE REQUIRED SECRET FILES
# ===========================================

# Get the repo root (parent of webui)
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Check for SOPS age keys
SOPS_KEY_FILE="${HOME}/.config/sops/age/keys.txt"
if [ ! -f "$SOPS_KEY_FILE" ]; then
    echo -e "${RED}Error: SOPS age keys not found at $(display_path "$SOPS_KEY_FILE")${NC}"
    echo "  These keys are required to decrypt secrets during deployment."
    echo "  Please ensure your SOPS age keys are in place before running this script."
    exit 1
fi
echo -e "${GREEN}Found SOPS keys: $(display_path "$SOPS_KEY_FILE")${NC}"

# Check for Terraform credentials
TF_CREDS_FILE="${REPO_ROOT}/terraform/cluster-create/credentials.auto.tfvars"
if [ ! -f "$TF_CREDS_FILE" ]; then
    echo -e "${RED}Error: Terraform credentials not found at $(display_path "$TF_CREDS_FILE")${NC}"
    echo "  This file contains Proxmox API credentials needed for VM deployment."
    echo "  Please create this file with your Proxmox credentials."
    exit 1
fi
echo -e "${GREEN}Found Terraform credentials: ${TF_CREDS_FILE}${NC}"

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

# ===========================================
# CHECK LXC TEMPLATE
# ===========================================

echo -e "${GREEN}[1/6] Checking LXC template on Proxmox...${NC}"
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

echo -e "${GREEN}[2/6] Creating Terraform configuration...${NC}"

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

echo -e "${GREEN}[3/6] Running Terraform...${NC}"
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
# SETUP VIA SINGLE PCT EXEC SESSION
# All setup in one SSH session to Proxmox
# Using the proven approach from commit 51b544b
# ===========================================

echo -e "${GREEN}[4/6] Setting up container via pct exec...${NC}"
echo -e "${YELLOW}  (One Proxmox password prompt for entire setup)${NC}"

# Read the GitHub SSH key content
GITHUB_SSH_KEY_CONTENT=$(cat "${GITHUB_SSH_KEY}")

# Clear old host keys for the container IP
ssh-keygen -R "${CONTAINER_IP}" 2>/dev/null || true

# Use pct exec via Proxmox SSH - this bypasses container SSH authentication entirely
# Everything runs in ONE session
proxmox_ssh "pct exec ${LXC_VMID} -- bash -c '
set -e

echo \"=== Installing packages ===\"
apt-get update && apt-get install -y sudo git locales

# Fix locale warnings
sed -i \"s/# en_US.UTF-8/en_US.UTF-8/\" /etc/locale.gen
locale-gen en_US.UTF-8

echo \"=== Creating non-root SSH user: ${SSH_USER} ===\"
useradd -m -s /bin/bash -G ${SSH_USER_GROUPS} ${SSH_USER} 2>/dev/null || echo \"User exists\"
echo \"${SSH_USER}:${SSH_USER_PASSWORD}\" | chpasswd
echo \"${SSH_USER} ALL=(ALL) NOPASSWD:ALL\" > /etc/sudoers.d/${SSH_USER}
chmod 440 /etc/sudoers.d/${SSH_USER}

echo \"=== Disabling root SSH login ===\"
sed -i \"s/^#*PermitRootLogin.*/PermitRootLogin no/\" /etc/ssh/sshd_config
systemctl restart ssh

echo \"=== Setting up GitHub SSH key for ${SSH_USER} ===\"
SSH_USER_HOME=\"/home/${SSH_USER}\"
mkdir -p \${SSH_USER_HOME}/.ssh
chmod 700 \${SSH_USER_HOME}/.ssh

cat > \${SSH_USER_HOME}/.ssh/github_deploy_key << \"KEYEOF\"
${GITHUB_SSH_KEY_CONTENT}
KEYEOF
chmod 600 \${SSH_USER_HOME}/.ssh/github_deploy_key

cat > \${SSH_USER_HOME}/.ssh/config << \"SSHCONFIG\"
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/github_deploy_key
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
SSHCONFIG
chmod 600 \${SSH_USER_HOME}/.ssh/config

chown -R ${SSH_USER}:${SSH_USER} \${SSH_USER_HOME}/.ssh

# Also setup root SSH for GitHub (WebUI runs as root and may need to git pull)
mkdir -p /root/.ssh
chmod 700 /root/.ssh
cp \${SSH_USER_HOME}/.ssh/github_deploy_key /root/.ssh/
cp \${SSH_USER_HOME}/.ssh/config /root/.ssh/
chmod 600 /root/.ssh/github_deploy_key /root/.ssh/config
ssh-keyscan -t ed25519,rsa github.com >> /root/.ssh/known_hosts 2>/dev/null

echo \"=== Testing GitHub connectivity ===\"
su - ${SSH_USER} -c \"ssh -T git@github.com 2>&1\" || true

echo \"=== Cloning repository (branch: ${GIT_BRANCH}) ===\"
# Create /opt/talos-cleanroom with correct ownership before cloning
mkdir -p /opt/talos-cleanroom
chown ${SSH_USER}:${SSH_USER} /opt/talos-cleanroom
su - ${SSH_USER} -c \"git clone -b ${GIT_BRANCH} ${GITHUB_REPO_URL} /opt/talos-cleanroom\"

# Add safe.directory for root (WebUI runs as root but repo owned by deploy user)
git config --global --add safe.directory /opt/talos-cleanroom

echo \"=== Running setup script ===\"
cd /opt/talos-cleanroom/webui/scripts
chmod +x setup-lxc.sh
./setup-lxc.sh --webui-password \"${WEBUI_PASSWORD}\"

echo \"=== Starting web UI service ===\"
systemctl start deployment-webui || echo \"Service may need manual start\"
systemctl status deployment-webui --no-pager || true

echo \"\"
echo \"=== Setup Complete ===\"
echo \"SSH user: ${SSH_USER}\"
echo \"Root SSH: disabled\"
'"

echo -e "${GREEN}[5/6] Container setup complete${NC}"

# ===========================================
# COPY SECRET FILES TO CONTAINER
# ===========================================

echo -e "${GREEN}[6/6] Copying secret files to container...${NC}"

# Wait for SSH to be ready on container
echo "  Waiting for container SSH..."
for i in {1..12}; do
    if ssh ${SSH_OPTS} ${SSH_USER}@${CONTAINER_IP} "echo ok" 2>/dev/null | grep -q ok; then
        echo -e "${GREEN}  Container SSH is ready${NC}"
        break
    fi
    sleep 5
done

# Copy SOPS age keys (to both deploy user and root, since WebUI runs as root)
echo "  Copying SOPS age keys..."
ssh ${SSH_OPTS} ${SSH_USER}@${CONTAINER_IP} "mkdir -p ~/.config/sops/age"
scp ${SSH_OPTS} "${SOPS_KEY_FILE}" ${SSH_USER}@${CONTAINER_IP}:~/.config/sops/age/keys.txt
# Also copy to root's home (WebUI service runs as root)
ssh ${SSH_OPTS} ${SSH_USER}@${CONTAINER_IP} "sudo mkdir -p /root/.config/sops/age && sudo cp ~/.config/sops/age/keys.txt /root/.config/sops/age/ && sudo chmod 600 /root/.config/sops/age/keys.txt"
echo -e "${GREEN}  SOPS keys copied (deploy + root)${NC}"

# Copy Terraform credentials
echo "  Copying Terraform credentials..."
scp ${SSH_OPTS} "${TF_CREDS_FILE}" ${SSH_USER}@${CONTAINER_IP}:/opt/talos-cleanroom/terraform/cluster-create/
echo -e "${GREEN}  Terraform credentials copied${NC}"

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
echo -e "${GREEN}Secret files have been automatically copied:${NC}"
echo "  - SOPS age keys"
echo "  - Terraform credentials"
echo ""
echo -e "${YELLOW}Recovery (if locked out):${NC}"
echo "  ssh root@${PROXMOX_HOST} 'pct exec ${LXC_VMID} -- bash'"
echo ""
