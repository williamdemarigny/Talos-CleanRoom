# Talos CleanRoom Deployment Web UI

A standalone web application for deploying and monitoring Talos Kubernetes clusters. This web UI provides a graphical interface for the deployment process defined in `DeployCluster.sh`.

## Features

- **User Authentication**: JWT-based authentication with configurable credentials
- **Configuration Editor**: View and manage cluster configuration (Terraform and Talos)
- **Real-time Deployment Monitoring**: WebSocket-based live updates during deployment
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

The `deploy-lxc.sh` script automates the entire deployment process including SSH key setup for the private repository.

1. **Run the deployment script**:
   ```bash
   cd deployment-webui
   ./deploy-lxc.sh
   ```

2. **Follow the prompts** to enter:
   - Proxmox API token
   - Proxmox SSH password
   - LXC container root password
   - Path to your GitHub SSH key (auto-detects common locations)

3. **Choose automatic setup** when prompted to complete the installation hands-free

4. **Copy SOPS keys** (required for deployment):
   ```bash
   ssh root@<container-ip> "mkdir -p /root/.config/sops/age"
   scp ~/.config/sops/age/keys.txt root@<container-ip>:/root/.config/sops/age/
   ```

5. **Access the UI** at `http://<container-ip>:8000`

#### Manual Deployment

If you prefer manual control, you can deploy step-by-step:

1. **Configure Terraform variables**:
   ```bash
   cd deployment-webui/terraform
   cp terraform.tfvars.example terraform.tfvars
   # Edit terraform.tfvars with your Proxmox credentials and network settings
   ```

2. **Deploy the LXC container**:
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

3. **Copy SSH key to container** (from your workstation):
   ```bash
   ssh root@<container-ip> "mkdir -p /root/.ssh && chmod 700 /root/.ssh"
   scp ~/.ssh/id_ed25519 root@<container-ip>:/root/.ssh/github_deploy_key
   ssh root@<container-ip> "chmod 600 /root/.ssh/github_deploy_key"
   ```

4. **SSH into the container and configure GitHub access**:
   ```bash
   ssh root@<container-ip>

   # Set up SSH config for GitHub
   chmod 600 /root/.ssh/github_deploy_key
   cat > /root/.ssh/config << 'EOF'
   Host github.com
       HostName github.com
       User git
       IdentityFile /root/.ssh/github_deploy_key
       IdentitiesOnly yes
       StrictHostKeyChecking accept-new
   EOF
   chmod 600 /root/.ssh/config
   ```

5. **Clone the repository and run setup**:
   ```bash
   # Clone via SSH (private repository)
   git clone git@github.com:williamdemarigny/Talos-CleanRoom.git /opt/talos-cleanroom

   # Run the setup script
   cd /opt/talos-cleanroom/deployment-webui/scripts
   chmod +x setup-lxc.sh
   ./setup-lxc.sh --webui-password your-secure-password
   ```

6. **Start the service**:
   ```bash
   systemctl start deployment-webui
   ```

7. **Access the UI** at `http://<container-ip>:8000`

#### Using a Bind Mount for the Repository

For persistent repository access from the Proxmox host, add a bind mount:

1. **On the Proxmox host**, edit `/etc/pve/lxc/<VMID>.conf`:
   ```
   mp0: /path/to/talos-cleanroom,mp=/opt/talos-cleanroom
   ```

2. **Restart the container**:
   ```bash
   pct stop <VMID>
   pct start <VMID>
   ```

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
   cd deployment-webui
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

- terraform
- kubectl
- helm
- talosctl
- talhelper
- sops
- jq
- curl
- git

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

### SOPS Keys

Copy your SOPS age keys to the container:

```bash
ssh root@<container-ip> "mkdir -p /root/.config/sops/age"
scp ~/.config/sops/age/keys.txt root@<container-ip>:/root/.config/sops/age/
```

## Service Management

```bash
# Start the service
systemctl start deployment-webui

# Stop the service
systemctl stop deployment-webui

# Check status
systemctl status deployment-webui

# View logs
journalctl -u deployment-webui -f

# Restart after configuration changes
systemctl restart deployment-webui
```

## Architecture

```
deployment-webui/
├── app/
│   ├── main.py              # FastAPI application
│   ├── config.py            # Application settings
│   ├── auth.py              # JWT authentication
│   ├── models/              # Pydantic models
│   ├── services/            # Business logic
│   │   ├── deployment_service.py  # Deployment orchestration
│   │   ├── config_service.py      # Configuration management
│   │   └── process_manager.py     # Subprocess execution
│   └── routers/             # API endpoints
├── static/                  # Frontend assets
├── templates/               # Jinja2 HTML templates
├── terraform/               # LXC container Terraform config
├── scripts/
│   └── setup-lxc.sh         # LXC setup script
├── Dockerfile               # Docker build (alternative)
└── docker-compose.yml       # Docker Compose (alternative)
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
- `POST /api/config/regenerate` - Regenerate Talos config
- `GET /api/config/validate` - Validate all configs

### Deployment
- `POST /api/deployment/start` - Start deployment
- `POST /api/deployment/abort` - Abort deployment
- `GET /api/deployment/status` - Get deployment status
- `GET /api/deployment/logs` - Get deployment logs
- `POST /api/deployment/cleanup` - Run terraform destroy

### System
- `GET /api/system/health` - Health check
- `GET /api/system/dependencies` - Check system dependencies

### WebSocket
- `WS /ws/deployment` - Real-time deployment updates

## Deployment Steps

The web UI executes the same steps as `DeployCluster.sh`:

1. Validate Git Repository
2. Check Dependencies
3. Terraform Deploy
4. Generate Talos Config
5. Apply Talos Configurations
6. Verify Cluster Health
7. Get Kubeconfig
8. Install ArgoCD
9. Deploy Infrastructure Stack
10. Enable ArgoCD Self-Management
11. Deploy OpenVAS
12. Deploy Faraday
13. Deploy Metasploit
14. Deploy Threat Dragon

## Security Considerations

1. **Change default credentials** before production use
2. **Use HTTPS** in production (configure via reverse proxy like Traefik)
3. **Secure the SECRET_KEY** - generated automatically by setup script
4. **Restrict network access** to the web UI
5. **SOPS keys** should be protected with proper file permissions
6. **GitHub SSH key** - Consider using a deploy key with read-only access instead of a personal SSH key

## Troubleshooting

### Common Issues

**Cannot clone repository (SSH key issues)**
- Verify the SSH key is copied to `/root/.ssh/github_deploy_key`
- Check permissions: `chmod 600 /root/.ssh/github_deploy_key`
- Verify SSH config exists: `cat /root/.ssh/config`
- Test GitHub connectivity: `ssh -T git@github.com`
- Ensure the SSH key has access to the repository in GitHub

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
# Application logs
journalctl -u deployment-webui -f

# Last 100 lines
journalctl -u deployment-webui -n 100

# Since specific time
journalctl -u deployment-webui --since "1 hour ago"
```

## Updating the Web UI

To update to a new version:

```bash
# Pull latest changes (SSH key must be configured)
cd /opt/talos-cleanroom
git pull

# Copy updated files
cp -r deployment-webui/app /opt/deployment-webui/
cp -r deployment-webui/static /opt/deployment-webui/
cp -r deployment-webui/templates /opt/deployment-webui/

# Restart service
systemctl restart deployment-webui
```

**Note**: The SSH key configured during initial setup is required for `git pull` to work with the private repository.

## License

This project is part of the Talos CleanRoom repository.
