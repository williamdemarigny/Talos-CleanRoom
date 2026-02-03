#!/bin/bash
# Talos CleanRoom Deployment Web UI - LXC Deployment Script
# Deploys the web UI as an LXC container on Proxmox
#
# Usage: ./deploy-lxc.sh [--yes]
#
# Options:
#   -y, --yes    Auto-confirm all prompts (non-interactive mode)
#
# Environment variables (set these to skip credential prompts):
#   PROXMOX_API_TOKEN    - Proxmox API token (format: user@pam!tokenid=secret)
#   PROXMOX_SSH_PASSWORD - Proxmox SSH password (skipped if SSH key auth works)
#   LXC_ROOT_PASSWORD    - LXC container root password
#   SSH_USER_PASSWORD    - SSH user password
#   GITHUB_SSH_KEY       - Path to GitHub SSH private key
#
# Example (fully automated):
#   export PROXMOX_API_TOKEN="root@pam!deploy=your-secret"
#   export LXC_ROOT_PASSWORD="secure-password"
#   export SSH_USER_PASSWORD="secure-password"
#   export GITHUB_SSH_KEY="$HOME/.ssh/id_ed25519"
#   ./deploy-lxc.sh --yes

set -eo pipefail

# Parse command line arguments
AUTO_CONFIRM=false
while [[ $# -gt 0 ]]; do
    case $1 in
        -y|--yes)
            AUTO_CONFIRM=true
            shift
            ;;
        -h|--help)
            head -25 "$0" | tail -20
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

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

# Deployment Settings (used by DeployCluster.sh)
LONGHORN_TIMEOUT=600             # Seconds to wait for Longhorn to be fully ready (10 min default)
ARGOCD_PASSWORD_RETRIES=5        # Retry attempts for ArgoCD password configuration

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

# Prompt for credentials if not set
if [ -z "$PROXMOX_API_TOKEN" ]; then
    echo -e "${YELLOW}Enter Proxmox API Token (format: user@pam!tokenid=secret):${NC}"
    read -r PROXMOX_API_TOKEN
fi

# Check if SSH key authentication works for Proxmox (skip password prompt if so)
if [ -z "$PROXMOX_SSH_PASSWORD" ]; then
    echo "  Checking SSH key authentication to Proxmox..."
    if ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new root@${PROXMOX_HOST} true 2>/dev/null; then
        echo -e "${GREEN}  ✓ SSH key authentication available - skipping password prompt${NC}"
        PROXMOX_SSH_PASSWORD=""
    else
        echo -e "${YELLOW}Enter Proxmox SSH password for root:${NC}"
        read -rs PROXMOX_SSH_PASSWORD
        echo ""
    fi
fi

if [ -z "$LXC_ROOT_PASSWORD" ]; then
    echo -e "${YELLOW}Enter password for LXC container root user:${NC}"
    read -rs LXC_ROOT_PASSWORD
    echo ""
fi

if [ -z "$SSH_USER_PASSWORD" ]; then
    echo -e "${YELLOW}Enter password for SSH user '${SSH_USER}':${NC}"
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
        echo -e "${YELLOW}Enter path to GitHub SSH private key [${DEFAULT_KEY}]:${NC}"
        read -r GITHUB_SSH_KEY
        GITHUB_SSH_KEY="${GITHUB_SSH_KEY:-$DEFAULT_KEY}"
    else
        echo -e "${YELLOW}Enter path to GitHub SSH private key:${NC}"
        read -r GITHUB_SSH_KEY
    fi
fi

# Validate SSH key exists
if [ ! -f "$GITHUB_SSH_KEY" ]; then
    echo -e "${RED}Error: SSH key not found at ${GITHUB_SSH_KEY}${NC}"
    exit 1
fi

echo -e "${GREEN}  Using SSH key: ${GITHUB_SSH_KEY}${NC}"

# Download LXC template to Proxmox if needed
echo -e "${GREEN}[1/5] Checking LXC template on Proxmox...${NC}"

TEMPLATE_NAME="debian-12-standard_12.12-1_amd64.tar.zst"
TEMPLATE_STORAGE="cephfs"

# SSH options for automated connections (accept new host keys, don't save to known_hosts)
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null"

# Check if template exists via SSH
echo "  Checking if template exists on Proxmox..."
TEMPLATE_EXISTS=$(ssh ${SSH_OPTS} -o ConnectTimeout=10 root@${PROXMOX_HOST} \
    "pveam list ${TEMPLATE_STORAGE} 2>/dev/null | grep -c '${TEMPLATE_NAME}'" 2>/dev/null || echo "0")

if [ "$TEMPLATE_EXISTS" = "0" ]; then
    echo -e "${YELLOW}  Template not found. Downloading to Proxmox...${NC}"
    ssh ${SSH_OPTS} root@${PROXMOX_HOST} \
        "pveam download ${TEMPLATE_STORAGE} ${TEMPLATE_NAME}" || {
        echo -e "${RED}  Failed to download template automatically.${NC}"
        echo -e "${YELLOW}  Please download manually on Proxmox:${NC}"
        echo "    pveam download ${TEMPLATE_STORAGE} ${TEMPLATE_NAME}"
        echo ""
        read -p "Press Enter once template is downloaded, or Ctrl+C to cancel..."
    }
else
    echo -e "${GREEN}  Template already exists on Proxmox${NC}"
fi

# Create terraform.tfvars
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

# Template Configuration (downloaded via pveam in step 1)
template_storage      = "cephfs"
lxc_template_filename = "${TEMPLATE_NAME}"

# Network Configuration
network_bridge  = "${NETWORK_BRIDGE}"
vlan_id         = ${VLAN_ID}
lxc_ip_address  = "${LXC_IP}"
lxc_gateway     = "${LXC_GATEWAY}"
lxc_mac_address = ""

# DNS Configuration
dns_domain  = "${DNS_DOMAIN}"
dns_servers = ${DNS_SERVERS}

# Authentication
lxc_root_password = "${LXC_ROOT_PASSWORD}"
ssh_public_keys   = []

# SSH User Configuration (non-root user for secure access)
ssh_user          = "${SSH_USER}"
ssh_user_password = "${SSH_USER_PASSWORD}"
ssh_user_groups   = "${SSH_USER_GROUPS}"

# Web UI Configuration
webui_admin_username = "${WEBUI_USER}"
webui_admin_password = "${WEBUI_PASSWORD}"
EOF

echo "  Configuration written to ${TERRAFORM_DIR}/terraform.tfvars"

# Initialize Terraform
echo -e "${GREEN}[3/5] Initializing Terraform...${NC}"
cd "${TERRAFORM_DIR}"
terraform init

# Plan deployment
echo -e "${GREEN}[4/5] Planning deployment...${NC}"
terraform plan -out=.tfplan

# Confirm deployment
echo ""
echo -e "${YELLOW}Ready to deploy LXC container with the following settings:${NC}"
echo "  Proxmox Host: ${PROXMOX_HOST}"
echo "  Container ID: ${LXC_VMID}"
echo "  Hostname:     ${LXC_HOSTNAME}"
echo "  IP Address:   ${LXC_IP}"
echo "  Resources:    ${LXC_CORES} cores, ${LXC_MEMORY}MB RAM, ${LXC_DISK}GB disk"
echo ""

if [[ "$AUTO_CONFIRM" == true ]]; then
    echo -e "${GREEN}Auto-confirming deployment (--yes flag)${NC}"
else
    read -p "Proceed with deployment? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Deployment cancelled."
        exit 0
    fi
fi

# Apply deployment
echo -e "${GREEN}[5/5] Deploying LXC container...${NC}"
terraform apply .tfplan

# Get container IP (strip CIDR notation)
CONTAINER_IP="${LXC_IP%/*}"

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}LXC Container Deployed Successfully!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Container IP: ${CONTAINER_IP}"
echo "SSH User:     ${SSH_USER}"
echo ""
echo -e "${YELLOW}Next Steps (Manual Setup):${NC}"
echo ""
echo "1. SSH into container as root (one-time setup):"
echo "   ssh root@${CONTAINER_IP}"
echo ""
echo "2. Create non-root SSH user with sudo access:"
echo "   useradd -m -s /bin/bash -G ${SSH_USER_GROUPS} ${SSH_USER}"
echo "   echo '${SSH_USER}:PASSWORD' | chpasswd"
echo "   echo '${SSH_USER} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/${SSH_USER}"
echo ""
echo "3. Copy SSH key and configure GitHub access (as ${SSH_USER}):"
echo "   ssh ${SSH_USER}@${CONTAINER_IP}"
echo "   mkdir -p ~/.ssh && chmod 700 ~/.ssh"
echo "   # Copy your GitHub deploy key to ~/.ssh/github_deploy_key"
echo "   chmod 600 ~/.ssh/github_deploy_key"
echo ""
echo "4. Clone the repository:"
echo "   git clone ${GITHUB_REPO_URL} /opt/Talos-CleanRoom"
echo ""
echo "5. Run the setup script:"
echo "   cd /opt/Talos-CleanRoom/deployment-webui/scripts"
echo "   sudo ./setup-lxc.sh --webui-password ${WEBUI_PASSWORD} --longhorn-timeout ${LONGHORN_TIMEOUT} --argocd-retries ${ARGOCD_PASSWORD_RETRIES}"
echo ""
echo "6. Copy SOPS keys (from your workstation):"
echo "   ssh ${SSH_USER}@${CONTAINER_IP} 'mkdir -p ~/.config/sops/age'"
echo "   scp ~/.config/sops/age/keys.txt ${SSH_USER}@${CONTAINER_IP}:~/.config/sops/age/"
echo ""
echo "7. Access the web UI:"
echo "   http://${CONTAINER_IP}:8000"
echo "   Login: ${WEBUI_USER} / ${WEBUI_PASSWORD}"
echo ""
echo -e "${GREEN}============================================${NC}"

# Optional: Run setup automatically
echo ""

if [[ "$AUTO_CONFIRM" == true ]]; then
    echo -e "${GREEN}Auto-confirming automatic setup (--yes flag)${NC}"
    REPLY="y"
else
    read -p "Run setup script automatically via SSH? (y/n) " -n 1 -r
    echo ""
fi

if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Remove any old host keys for this IP (container may have been recreated)
    echo -e "${GREEN}Clearing old SSH host keys for ${CONTAINER_IP}...${NC}"
    ssh-keygen -R "${CONTAINER_IP}" 2>/dev/null || true

    echo -e "${GREEN}Waiting for container to be ready...${NC}"

    # Wait for container to be running (check via Proxmox)
    MAX_WAIT=60
    WAIT_INTERVAL=5
    ELAPSED=0

    while [ $ELAPSED -lt $MAX_WAIT ]; do
        CONTAINER_STATUS=$(ssh ${SSH_OPTS} root@${PROXMOX_HOST} "pct status ${LXC_VMID} 2>/dev/null | grep -o 'running'" || echo "")
        if [ "$CONTAINER_STATUS" = "running" ]; then
            echo -e "${GREEN}  Container is running after ${ELAPSED} seconds${NC}"
            sleep 3  # Give container services time to start
            break
        fi
        echo "  Waiting for container... (${ELAPSED}/${MAX_WAIT}s)"
        sleep $WAIT_INTERVAL
        ELAPSED=$((ELAPSED + WAIT_INTERVAL))
    done

    if [ $ELAPSED -ge $MAX_WAIT ]; then
        echo -e "${RED}Error: Timed out waiting for container to start${NC}"
        echo "  Check container status: ssh root@${PROXMOX_HOST} 'pct status ${LXC_VMID}'"
        exit 1
    fi

    # Read the GitHub SSH key content for transfer
    GITHUB_SSH_KEY_CONTENT=$(cat "${GITHUB_SSH_KEY}")

    echo -e "${GREEN}Running setup via Proxmox pct exec (no container password needed)...${NC}"

    # Use pct exec via Proxmox SSH - this bypasses container SSH authentication entirely
    ssh ${SSH_OPTS} root@${PROXMOX_HOST} "pct exec ${LXC_VMID} -- bash -c '
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

echo \"=== Testing GitHub connectivity ===\"
su - ${SSH_USER} -c \"ssh -T git@github.com 2>&1\" || true

echo \"=== Cloning/Updating repository ===\"
if [ -d /opt/Talos-CleanRoom/.git ]; then
    echo \"Repository already exists, pulling latest changes...\"
    chown -R ${SSH_USER}:${SSH_USER} /opt/Talos-CleanRoom
    su - ${SSH_USER} -c \"cd /opt/Talos-CleanRoom && git pull\"
else
    # Remove directory if it exists but is not a git repo
    rm -rf /opt/Talos-CleanRoom 2>/dev/null || true
    mkdir -p /opt/Talos-CleanRoom
    chown ${SSH_USER}:${SSH_USER} /opt/Talos-CleanRoom
    su - ${SSH_USER} -c \"git clone ${GITHUB_REPO_URL} /opt/Talos-CleanRoom\"
fi

echo \"=== Running setup script ===\"
cd /opt/Talos-CleanRoom/deployment-webui/scripts
chmod +x setup-lxc.sh
./setup-lxc.sh --webui-password \"${WEBUI_PASSWORD}\" --longhorn-timeout ${LONGHORN_TIMEOUT} --argocd-retries ${ARGOCD_PASSWORD_RETRIES}

echo \"=== Starting web UI service ===\"
systemctl start deployment-webui || echo \"Service may need manual start\"
systemctl status deployment-webui --no-pager || true

echo \"\"
echo \"=== Setup Complete ===\"
echo \"SSH user: ${SSH_USER}\"
echo \"Root SSH: disabled\"
'"

    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}Setup Complete!${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""

    # Automatically copy secrets using pct push via Proxmox (no container password needed)
    echo -e "${GREEN}Copying secrets to container via Proxmox...${NC}"

    # Copy SOPS age keys
    SOPS_KEY_FILE="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"
    if [ -f "$SOPS_KEY_FILE" ]; then
        echo "  Copying SOPS age keys..."
        # Create directories in container
        ssh ${SSH_OPTS} root@${PROXMOX_HOST} "pct exec ${LXC_VMID} -- mkdir -p /home/${SSH_USER}/.config/sops/age /root/.config/sops/age"
        # Copy to Proxmox host first, then push to container
        scp ${SSH_OPTS} "$SOPS_KEY_FILE" root@${PROXMOX_HOST}:/tmp/sops_keys.txt
        ssh ${SSH_OPTS} root@${PROXMOX_HOST} "pct push ${LXC_VMID} /tmp/sops_keys.txt /home/${SSH_USER}/.config/sops/age/keys.txt"
        ssh ${SSH_OPTS} root@${PROXMOX_HOST} "pct push ${LXC_VMID} /tmp/sops_keys.txt /root/.config/sops/age/keys.txt"
        ssh ${SSH_OPTS} root@${PROXMOX_HOST} "pct exec ${LXC_VMID} -- chown -R ${SSH_USER}:${SSH_USER} /home/${SSH_USER}/.config"
        ssh ${SSH_OPTS} root@${PROXMOX_HOST} "rm /tmp/sops_keys.txt"
        echo -e "${GREEN}  ✓ SOPS keys copied${NC}"
    else
        echo -e "${YELLOW}  Warning: SOPS key file not found at $SOPS_KEY_FILE${NC}"
        echo "  You will need to copy it manually:"
        echo "    scp ~/.config/sops/age/keys.txt ${SSH_USER}@${CONTAINER_IP}:~/.config/sops/age/"
    fi

    # Copy Terraform credentials
    # SCRIPT_DIR is deployment-webui/, so go up one level to get repo root
    REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
    TF_CREDS_FILE="${REPO_ROOT}/Resources/IAC-DNS/terraform/talos-cluster-create/credentials.auto.tfvars"
    if [ -f "$TF_CREDS_FILE" ]; then
        echo "  Copying Terraform credentials..."
        # Copy to Proxmox host first, then push to container
        scp ${SSH_OPTS} "$TF_CREDS_FILE" root@${PROXMOX_HOST}:/tmp/credentials.auto.tfvars
        ssh ${SSH_OPTS} root@${PROXMOX_HOST} "pct push ${LXC_VMID} /tmp/credentials.auto.tfvars /opt/Talos-CleanRoom/Resources/IAC-DNS/terraform/talos-cluster-create/credentials.auto.tfvars"
        ssh ${SSH_OPTS} root@${PROXMOX_HOST} "rm /tmp/credentials.auto.tfvars"
        echo -e "${GREEN}  ✓ Terraform credentials copied${NC}"
    else
        echo -e "${YELLOW}  Warning: Terraform credentials not found at $TF_CREDS_FILE${NC}"
        echo "  You will need to copy them manually:"
        echo "    scp Resources/IAC-DNS/terraform/talos-cluster-create/credentials.auto.tfvars \\"
        echo "        ${SSH_USER}@${CONTAINER_IP}:/opt/Talos-CleanRoom/Resources/IAC-DNS/terraform/talos-cluster-create/"
    fi

    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}Deployment Ready!${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo "Web UI is now running at: http://${CONTAINER_IP}:8000"
    echo ""
    echo -e "${YELLOW}SSH Access (root login disabled):${NC}"
    echo "  ssh ${SSH_USER}@${CONTAINER_IP}"
    echo "  Password: (the one you entered during setup)"
    echo ""
fi
