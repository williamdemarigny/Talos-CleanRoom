# Technical Architecture: LXC Deployment Console

This document provides technical details on how the LXC container delivers the Talos CleanRoom Deployment Console. For setup and usage instructions, see [README.md](README.md).

> **Note:** Security scanning has moved to the [Scanning Console](../scanning-app/) (runs in K8s). This document covers deployment/cluster-lifecycle only.

## Overview

The Deployment Console runs as a FastAPI application inside a Debian 12 LXC container on Proxmox. The container is provisioned via Terraform and configured with a systemd service that exposes the application on port 8000.

```
┌─────────────────────────────────────────────────────────────┐
│                     PROXMOX HOST                            │
│  ┌───────────────────────────────────────────────────────┐  │
│  │           LXC Container (Debian 12)                   │  │
│  │                                                       │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │              FastAPI Application                │  │  │
│  │  │  ┌─────────┐ ┌─────────┐ ┌─────────────────┐   │  │  │
│  │  │  │ Routers │ │Services │ │ WebSocket Mgrs  │   │  │  │
│  │  │  └────┬────┘ └────┬────┘ └────────┬────────┘   │  │  │
│  │  │       └───────────┴───────────────┘            │  │  │
│  │  │                   ↓                            │  │  │
│  │  │         ProcessManager (subprocess)            │  │  │
│  │  │                   ↓                            │  │  │
│  │  │   terraform │ talosctl │ kubectl │ helm        │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  │                                                       │  │
│  │  Uvicorn ASGI Server → Port 8000                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                           ↓                                  │
│                    Bridge Network                            │
└─────────────────────────────────────────────────────────────┘
                            ↓
                      Browser Client
```

## Technology Stack

| Layer | Technology | Version |
|-------|------------|---------|
| Runtime | Python | 3.11 |
| Web Framework | FastAPI | 0.109.0 |
| ASGI Server | Uvicorn | 0.27.0 |
| Frontend JS | Alpine.js | 3.x (CDN) |
| CSS Framework | Tailwind CSS | 3.x (CDN) |
| Templating | Jinja2 | 3.1.3 |
| Authentication | python-jose (JWT) | 3.3.0 |
| Password Hashing | bcrypt | 4.0.1 |
| Real-time | websockets | 12.0 |
| Container | Debian 12 LXC | - |
| Provisioning | Terraform (BPG) | 0.82.1 |

## Container Construction

### 1. Terraform Provisioning

The LXC container is created via Terraform using the BPG Proxmox provider.

**Key resource:** `terraform/main.tf`

```hcl
resource "proxmox_virtual_environment_container" "deployment_webui" {
  node_name   = var.proxmox_node
  vm_id       = var.lxc_vmid
  unprivileged = true

  operating_system {
    template_file_id = "cephfs:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst"
  }

  cpu { cores = var.lxc_cores }
  memory { dedicated = var.lxc_memory }

  network_interface {
    name   = "eth0"
    bridge = var.network_bridge
  }

  features { nesting = true }
}
```

### 2. System Setup

The `scripts/setup-lxc.sh` script runs inside the container to install dependencies:

1. System packages (curl, git, jq, unzip)
2. kubectl v1.29
3. Helm 3
4. Terraform 1.7.0
5. talosctl (latest)
6. talhelper (latest)
7. SOPS v3.8.1
8. Python 3.11 venv with application dependencies

### 3. Systemd Service

The application runs as a systemd unit:

```ini
[Unit]
Description=Talos Deployment WebUI
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/deployment-webui
ExecStart=/opt/deployment-webui/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

## Application Architecture

### Backend Structure

```
app/
├── main.py                 # FastAPI initialization, page routes, middleware
├── config.py               # Pydantic settings (env vars, defaults)
├── auth.py                 # JWT token creation/validation, password hashing
├── models/
│   ├── config.py           # TerraformConfig, TalosEnvConfig, validation models
│   ├── deployment.py       # DeploymentState, DeploymentStep, LogEntry
│   └── common.py           # Shared base models (BaseStatus, BaseLogEntry)
├── routers/
│   ├── auth.py             # POST /api/auth/login, logout, me, redeem-code
│   ├── config.py           # GET/PUT /api/config/*
│   ├── deployment.py       # POST /api/deployment/start, abort, cleanup
│   └── websocket.py        # WS /ws/deployment
└── services/
    ├── config_service.py       # Terraform/Talos config parsing & validation
    ├── deployment_service.py   # 16-step deployment orchestration
    └── process_manager.py      # Async subprocess execution with streaming
```

### Request Flow

```
HTTP Request
     ↓
FastAPI Router (JWT auth middleware)
     ↓
Service Layer (business logic)
     ↓
ProcessManager (spawns subprocess)
     ↓
System Tool (terraform, kubectl, etc.)
     ↓
Output captured → LogEntry created
     ↓
WebSocket broadcast to all clients
     ↓
Browser updates UI in real-time
```

### Authentication

- **Method:** JWT Bearer tokens
- **Storage:** HttpOnly cookie + localStorage fallback
- **Expiry:** 8 hours (configurable)
- **Password:** bcrypt hashed, stored in `.env`

### WebSocket Connections

One WebSocket endpoint serves real-time deployment updates:

| Endpoint | Manager | Purpose |
|----------|---------|---------|
| `WS /ws/deployment` | `ConnectionManager` | Deployment log streaming + step updates |

Uses a connection manager pattern with broadcast to all connected clients:

```python
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)
```

### Deployment Orchestration

The `DeploymentService` manages 16 sequential steps:

| Step | Description |
|------|-------------|
| 1 | Validate Git repository |
| 2 | Check dependencies |
| 3 | Terraform deploy (Proxmox VMs) |
| 4 | Wait for VMs to be ready |
| 5 | Generate Talos config |
| 6 | Apply Talos configurations |
| 7 | Verify cluster health |
| 8 | Get kubeconfig |
| 9 | Install ArgoCD |
| 10 | Deploy infrastructure stack (MetalLB, cert-manager, Traefik, Ceph CSI) |
| 11 | Enable ArgoCD self-management |
| 12-15 | Deploy security tools (OpenVAS, Faraday, Metasploit, Threat Dragon) |
| 16 | Configure integrations |

Each step executes via `ProcessManager`, which streams stdout/stderr to connected WebSocket clients. State is persisted to disk with Fernet encryption (survives webapp restarts).

## Frontend Architecture

### Templates (Jinja2)

| Template | Purpose |
|----------|---------|
| `base.html` | Layout, nav (Dashboard/Config/Deploy/Logs), CDN imports |
| `dashboard.html` | Status overview, dependency checks, quick actions |
| `config.html` | Terraform/Talos config editor with tabs |
| `deployment.html` | Live deployment progress with step tracker |
| `logs.html` | Paginated log viewer with step filtering |
| `login.html` | Authentication form |

### Alpine.js Components

| File | Component | Purpose |
|------|-----------|---------|
| `app.js` | (shared) | Auth utilities, fetch wrappers, formatting |
| `deployment.js` | `deploymentMonitor` | Deployment progress, WebSocket + REST polling |
| `websocket.js` | `DeploymentWebSocket` | WebSocket connection with auto-reconnect |

### Styling

Tailwind CSS via CDN with custom utilities in `static/css/custom.css`.

## Network Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Port | 8000 | Uvicorn listen port |
| Bridge | vmbr0 | Proxmox network bridge |
| VLAN | 3 | VLAN tagging |
| IP | 10.83.3.190/24 | Static IP (configured via Terraform) |

## Key Files Reference

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI initialization + page routes |
| `app/services/deployment_service.py` | 16-step deployment orchestration |
| `scripts/setup-lxc.sh` | Container setup script |
| `terraform/main.tf` | LXC resource definition |
| `deploy-lxc.sh` | Automated deployment script |
| `requirements.txt` | Python dependencies |

## Docker Alternative

For non-Proxmox environments, the same application runs in Docker:

```dockerfile
FROM python:3.11-slim
# Install system tools (kubectl, helm, terraform, etc.)
COPY requirements.txt .
RUN pip install -r requirements.txt
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

See `docker-compose.yml` for volume mounts and network configuration.
