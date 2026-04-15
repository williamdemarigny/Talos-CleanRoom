# Talos CleanRoom Deployment Console

A standalone web application for deploying and monitoring Talos Kubernetes clusters. This console provides a graphical interface for cluster provisioning and lifecycle management.

> **Note:** Security scanning (Nmap, OpenVAS, Metasploit, LOKI-RS) has moved to the [Scanning Console](../scanning-app/), which runs in-cluster as a K8s deployment. See `docs/vuln-management-plan.md` for details.

## Features

- **User Authentication**: JWT-based authentication with configurable credentials
- **Configuration Editor**: View and manage cluster configuration (Terraform and Talos)
- **Real-time Deployment Monitoring**: WebSocket-based live updates during deployment
- **Cross-Domain Auth**: One-time code exchange for SSO with Scanning Console and Portal
- **Log Streaming**: Real-time log output from deployment steps
- **Dependency Checking**: Verify all required tools are installed before deployment

## Deployment Options

### Option 1: LXC Container on Proxmox (Recommended)

Deploy as a lightweight LXC container on your Proxmox cluster using Terraform.

#### Prerequisites

- Proxmox VE 7.x or 8.x
- Terraform installed on your workstation
- Proxmox API token with appropriate permissions
- Network connectivity to Proxmox host
- **SSH key with access to the private GitHub repository** (e.g., `~/.ssh/id_ed25519`)

#### Quick Start (Automated)

The `deploy-lxc.sh` script automates the entire deployment process:

1. **Run the deployment script**:
   ```bash
   cd webui
   ./deploy-lxc.sh
   ```

2. **Follow the prompts** to enter:
   - Proxmox API token
   - Proxmox SSH password
   - LXC container root password
   - Deploy user password (for SSH access)
   - Path to your GitHub SSH key (auto-detects common locations)

3. The script will:
   - Create the LXC container via Terraform
   - Set up a `deploy` user with sudo access (root SSH is disabled)
   - Clone the repository and run the setup script
   - Copy SOPS keys and Terraform credentials automatically

4. **Access the UI** at `http://10.83.3.190:8000`

#### Manual Deployment

If you prefer manual control:

1. **Configure Terraform variables**:
   ```bash
   cd webui/terraform
   # Edit terraform.tfvars with your Proxmox credentials and network settings
   ```

2. **Deploy the LXC container**:
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

3. **SSH into the container** and set up:
   ```bash
   ssh deploy@<container-ip>
   sudo -i

   # Clone via SSH (private repository)
   git clone git@github.com:williamdemarigny/Talos-CleanRoom.git /opt/talos-cleanroom

   # Run the setup script
   cd /opt/talos-cleanroom/webui/scripts
   chmod +x setup-lxc.sh
   ./setup-lxc.sh --webui-password your-secure-password

   # Start the service
   systemctl start deployment-webui
   ```

4. **Access the UI** at `http://<container-ip>:8000`

#### Terraform Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `proxmox_api_url` | - | Proxmox API URL (required) |
| `proxmox_api_token` | - | Proxmox API token (required) |
| `lxc_vmid` | `200` | VM ID for the container |
| `lxc_hostname` | `deployment-webui` | Container hostname |
| `lxc_cores` | `2` | CPU cores |
| `lxc_memory` | `2048` | Memory in MB |
| `lxc_disk_size` | `20` | Root disk size in GB |
| `lxc_ip_address` | - | Static IP in CIDR notation (required) |
| `lxc_gateway` | - | Default gateway (required) |
| `network_bridge` | `vmbr0` | Proxmox network bridge |
| `vlan_id` | `0` | VLAN ID (0 for no VLAN) |

### Option 2: Docker Container

Deploy as a Docker container for environments without Proxmox.

1. **Configure environment**:
   ```bash
   cd webui
   cp .env.example .env
   # Edit .env with your settings
   ```

2. **Start the container**:
   ```bash
   docker compose up -d
   ```

3. **Access the UI** at `http://localhost:8000`

## Default Credentials

- Username: `admin`
- Password: `admin`

**Important**: Change these credentials in production!

## System Dependencies

The following tools are installed in the LXC container (or Docker image):

- terraform, kubectl, helm, talosctl, talhelper, sops, jq, curl, git

## Configuration

### Web UI Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_USERNAME` | `admin` | Admin username |
| `ADMIN_PASSWORD_HASH` | (bcrypt hash) | Bcrypt hash of admin password |
| `SECRET_KEY` | (generated) | JWT signing key |
| `ACCESS_TOKEN_EXPIRE_HOURS` | `8` | Token expiration time |
| `REPO_ROOT` | `/opt/talos-cleanroom` | Path to repository |
| `MASTER_NODE` | `talos-CleanRoom-master-01.knowledgeondemand.net` | Master node FQDN |

## Service Management

```bash
systemctl start deployment-webui     # Start
systemctl stop deployment-webui      # Stop
systemctl status deployment-webui    # Check status
journalctl -u deployment-webui -f    # View logs
systemctl restart deployment-webui   # Restart after changes
```

## Architecture

```
webui/
├── app/
│   ├── main.py                      # FastAPI application + page routes
│   ├── config.py                    # Application settings
│   ├── auth.py                      # JWT authentication
│   ├── models/
│   │   ├── config.py                # Configuration data models
│   │   ├── deployment.py            # Deployment state models
│   │   └── common.py                # Shared base models
│   ├── services/
│   │   ├── deployment_service.py    # Deployment orchestration
│   │   ├── config_service.py        # Configuration management
│   │   └── process_manager.py       # Subprocess execution
│   └── routers/
│       ├── auth.py                  # Authentication endpoints
│       ├── config.py                # Configuration endpoints
│       ├── deployment.py            # Deployment endpoints
│       └── websocket.py             # Deployment WebSocket
├── static/
│   ├── css/custom.css               # Tailwind custom utilities
│   └── js/
│       ├── app.js                   # Shared utilities (auth, fetch, formatting)
│       ├── deployment.js            # Deployment monitor component
│       └── websocket.js             # WebSocket connection manager
├── templates/
│   ├── base.html                    # Layout with nav (Dashboard, Config, Deploy, Logs)
│   ├── login.html                   # Authentication form
│   ├── dashboard.html               # Status overview
│   ├── config.html                  # Terraform/Talos config editor
│   ├── deployment.html              # Deployment progress monitor
│   └── logs.html                    # Paginated log viewer
├── terraform/                       # LXC container Terraform config
├── scripts/
│   └── setup-lxc.sh                 # LXC setup script
├── deploy-lxc.sh                    # Automated LXC deployment
├── Dockerfile                       # Docker build (alternative)
├── docker-compose.yml               # Docker Compose (alternative)
└── requirements.txt                 # Python dependencies
```

## API Endpoints

### Authentication
- `POST /api/auth/login` - Login and get JWT token
- `POST /api/auth/logout` - Logout
- `GET /api/auth/me` - Get current user info

### Configuration
- `GET /api/config/terraform` - Get Terraform config
- `PUT /api/config/terraform` - Update Terraform config
- `GET /api/config/talos/env` - Get Talos environment
- `GET /api/config/talos/config` - Get Talos cluster config
- `GET /api/config/all` - Get all configs at once
- `POST /api/config/regenerate` - Regenerate Talos config
- `GET /api/config/validate` - Validate all configs

### Deployment
- `POST /api/deployment/start` - Start deployment
- `POST /api/deployment/abort` - Abort deployment
- `POST /api/deployment/resume` - Resume a failed or aborted deployment
- `POST /api/deployment/skip-step` - Skip a failed step and resume
- `GET /api/deployment/status` - Get deployment status
- `GET /api/deployment/logs` - Get deployment logs
- `GET /api/deployment/kubeconfig` - Download kubeconfig
- `GET /api/deployment/credentials` - Get service credentials
- `POST /api/deployment/cleanup` - Run terraform destroy

### Cross-Domain Auth
- `POST /api/auth/redeem-code` - Redeem one-time auth code (from Portal SSO)

### System
- `GET /api/system/health` - Health check
- `GET /api/system/dependencies` - Check system dependencies

### WebSocket
- `WS /ws/deployment` - Real-time deployment updates

## Web UI Pages

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/` | Status overview, dependency checks, quick actions |
| Configuration | `/config` | Terraform/Talos config viewer and editor |
| Deployment | `/deployment` | Real-time deployment progress with step tracker |
| Logs | `/logs` | Paginated deployment log viewer |

## Deployment Steps

The web UI orchestrates a 16-step cluster deployment:

1. Validate Git Repository
2. Check Dependencies
3. Terraform Deploy (create Proxmox VMs)
4. Wait for VMs
5. Generate Talos Config
6. Apply Talos Configurations
7. Verify Cluster Health
8. Get Kubeconfig
9. Install ArgoCD
10. Deploy Infrastructure Stack (MetalLB, cert-manager, Traefik, Ceph CSI)
11. Enable ArgoCD Self-Management
12. Deploy OpenVAS
13. Deploy Faraday
14. Deploy Metasploit
15. Deploy Threat Dragon
16. Configure Integrations

## Security Considerations

1. **Change default credentials** before production use
2. **Use HTTPS** in production (configure via reverse proxy like Traefik)
3. **Secure the SECRET_KEY** - generated automatically by setup script
4. **Restrict network access** to the web UI
5. **SOPS keys** should be protected with proper file permissions
6. **GitHub SSH key** - Consider using a deploy key with read-only access

## Troubleshooting

### Common Issues

**Container cannot resolve DNS**
- Verify DNS servers in Terraform config
- Check `/etc/resolv.conf` inside the container

**Cannot connect to WebSocket**
- Verify the service is running: `systemctl status deployment-webui`
- Check firewall rules on Proxmox host

**Deployment fails at Terraform step**
- Verify Proxmox credentials in the main cluster Terraform config
- Check network connectivity from container to Proxmox host

**Missing dependencies after setup**
- Re-run the setup script: `./setup-lxc.sh`
- Check individual tool versions: `terraform version`, `kubectl version`, etc.

**Authentication fails**
- Verify password hash in `/opt/deployment-webui/.env`
- Regenerate password:
  ```bash
  python3 -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('your-password'))"
  ```

### Viewing Logs

```bash
journalctl -u deployment-webui -f          # Live logs
journalctl -u deployment-webui -n 100      # Last 100 lines
journalctl -u deployment-webui --since "1 hour ago"
```

## Updating the Web UI

The application is symlinked from the cloned repository, so `git pull` updates the running code:

```bash
ssh deploy@10.83.3.190
cd /opt/talos-cleanroom
git pull

# Restart to pick up changes
sudo systemctl restart deployment-webui
```
