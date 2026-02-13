# Technical Architecture: LXC WebUI

This document provides technical details on how the LXC container delivers the Talos CleanRoom deployment WebUI. For setup and usage instructions, see [README.md](README.md).

## Overview

The WebUI runs as a FastAPI application inside a Debian 12 LXC container on Proxmox. The container is provisioned via Terraform and configured with a systemd service that exposes the application on port 8000.

```
┌─────────────────────────────────────────────────────────────┐
│                     PROXMOX HOST                            │
│  ┌───────────────────────────────────────────────────────┐  │
│  │           LXC Container (Debian 12)                   │  │
│  │                                                       │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │              FastAPI Application                │  │  │
│  │  │  ┌─────────┐ ┌─────────┐ ┌─────────────────┐   │  │  │
│  │  │  │ Routers │ │Services │ │ WebSocket Mgr   │   │  │  │
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
    template_file_id = "local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst"
  }

  cpu { cores = var.lxc_cores }
  memory { dedicated = var.lxc_memory }

  network_interface {
    name   = "eth0"
    bridge = var.network_bridge
  }
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
├── main.py                 # FastAPI app initialization, middleware, routes
├── config.py               # Pydantic settings (env vars, defaults)
├── auth.py                 # JWT token creation/validation, password hashing
├── models/
│   ├── config.py           # Configuration data models
│   └── deployment.py       # DeploymentState, DeploymentStep, LogEntry
├── routers/
│   ├── auth.py             # POST /api/auth/login, logout
│   ├── config.py           # GET/PUT /api/config/*
│   ├── deployment.py       # POST /api/deployment/start, abort, cleanup
│   └── websocket.py        # WS /ws/deployment
└── services/
    ├── config_service.py   # Terraform/Talos config parsing & validation
    ├── deployment_service.py # 14-step deployment orchestration
    └── process_manager.py  # Async subprocess execution with streaming
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
- **Storage:** LocalStorage (client-side)
- **Expiry:** 8 hours (configurable)
- **Password:** bcrypt hashed, stored in `.env`

```python
# Token validation flow (auth.py)
credentials = HTTPBearer()
token = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
```

### WebSocket Connection

Real-time updates use a connection manager pattern:

```python
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)
```

**Message types:**
- `log` - New log entry
- `step_update` - Step status changed
- `initial_state` - Full state on connect
- `ping/pong` - Keep-alive

### Deployment Orchestration

The `DeploymentService` manages 14 sequential steps:

| Step | Description |
|------|-------------|
| 1 | Validate Git repository |
| 2 | Check dependencies |
| 3 | Terraform deploy (Proxmox VMs) |
| 4 | Generate Talos config |
| 5 | Apply Talos configurations |
| 6 | Verify cluster health |
| 7 | Get kubeconfig |
| 8 | Install ArgoCD |
| 9 | Deploy infrastructure stack |
| 10 | Enable ArgoCD self-management |
| 11-14 | Deploy security tools |

Each step executes via `ProcessManager`, which streams stdout/stderr to connected WebSocket clients.

## Frontend Architecture

### Templates (Jinja2)

| Template | Purpose |
|----------|---------|
| `base.html` | Layout, nav, Tailwind/Alpine CDN imports |
| `dashboard.html` | Status overview, dependency checks |
| `deployment.html` | Live deployment progress |
| `config.html` | Terraform/Talos config editor |
| `logs.html` | Paginated log viewer |
| `login.html` | Authentication form |

### Alpine.js Components

**deployment.js** - Main deployment monitor:
```javascript
Alpine.data('deploymentMonitor', () => ({
    status: 'idle',
    steps: [],
    logs: [],
    ws: null,

    init() {
        this.connectWebSocket();
    },

    connectWebSocket() {
        this.ws = new WebSocket(`ws://${location.host}/ws/deployment`);
        this.ws.onmessage = (e) => this.handleMessage(JSON.parse(e.data));
    }
}));
```

### Styling

Tailwind CSS via CDN with custom utilities in `static/css/custom.css`.

## Network Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Port | 8000 | Uvicorn listen port |
| Bridge | vmbr0 | Proxmox network bridge |
| VLAN | 0 (none) | Optional VLAN tagging |
| IP | Static | Configured via Terraform |

## Key Files Reference

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI initialization |
| `app/services/deployment_service.py` | Deployment orchestration |
| `app/routers/websocket.py` | Real-time updates |
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
