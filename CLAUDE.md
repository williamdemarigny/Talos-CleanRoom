# Claude Code Primer — Talos CleanRoom

> **Purpose:** Bring Claude up to speed at the start of every thread. Read this before making changes.
> Auto-memory at `~/.claude/projects/.../memory/MEMORY.md` has additional lessons learned.

## What This Project Is

A complete Infrastructure-as-Code platform for deploying a Talos Kubernetes cluster on Proxmox, with an integrated security toolchain (OpenVAS, Metasploit, Faraday, LOKI-RS IOC scanner) and a web-based deployment/scanning UI. Everything is GitOps-managed via ArgoCD.

**Current branch:** `refactor/restructure`
**Git remote:** `git@github.com:williamdemarigny/Talos-CleanRoom.git`

---

## Architecture Overview

```
Proxmox Cluster (4 nodes: pve01-04, 10.83.2.20-23)
  │
  ├── Talos K8s Cluster (VLAN 3: 10.83.3.0/24)
  │     ├── Control Plane: master-01 (VMID 2000, 10.83.3.10)
  │     ├── Workers: worker-01..03 (VMIDs 3001-3003, 10.83.3.15-17)
  │     ├── Pod CIDR: 10.14.0.0/16, Service CIDR: 10.15.0.0/16
  │     ├── Storage: Ceph RBD (Proxmox-managed, 4 monitors)
  │     └── MetalLB IP Pool: 10.83.3.200-250 (L2 mode)
  │
  ├── LXC: deployment-webui (VMID 200, 10.83.3.190) — FastAPI WebUI
  └── LXC: build-vm (VMID 201, 10.83.3.191) — Docker image builds
```

**Ingress path:** Internet → MetalLB (10.83.3.200) → Traefik → K8s Services
**DNS:** All services at `*.knowledgeondemand.net` resolve to Traefik LB IP
**TLS:** Wildcard cert via cert-manager + Cloudflare DNS-01

---

## Repository Structure

```
Talos-CleanRoom/
├── webui/                    # FastAPI Deployment + Scanning WebUI (runs in LXC)
│   ├── app/
│   │   ├── main.py           # FastAPI app — mounts routers, static, templates, page routes
│   │   ├── auth.py           # JWT (HS256, 8hr) + bcrypt, HttpOnly cookies + Bearer header
│   │   ├── config.py         # Pydantic BaseSettings, @lru_cache singleton
│   │   ├── models/           # Pydantic models
│   │   │   ├── common.py     # BaseStatus enum, BaseLogEntry
│   │   │   ├── deployment.py # DeploymentState, DeploymentStep, StepStatus, DEPLOYMENT_STEPS[]
│   │   │   ├── scan.py       # ScanState, ScanTool, ScanProfile, ScanToolState, ScanRequest
│   │   │   ├── ioc_scan.py   # IocScanState, MountType, IocFinding, IocScanRequest
│   │   │   └── config.py     # NodeConfig, NetworkConfig, TerraformConfig
│   │   ├── routers/
│   │   │   ├── auth.py       # POST /api/auth/login, /logout, GET /me
│   │   │   ├── deployment.py # POST start/abort, GET status/logs/kubeconfig/credentials, POST cleanup
│   │   │   ├── config.py     # GET/PUT terraform, GET talos/env, talos/config, all, validate
│   │   │   ├── scan.py       # POST start/abort, GET status/history/modules/openvas-*/logs, WS ws
│   │   │   ├── ioc_scan.py   # POST start/abort, GET status/history/logs, WS ws
│   │   │   ├── websocket.py  # WS /ws/deployment (deployment real-time updates)
│   │   │   └── ws_manager.py # ConnectionManager (Set[WebSocket] + broadcast), create_message()
│   │   └── services/
│   │       ├── deployment_service.py  # 17-step cluster orchestrator (~1660 lines)
│   │       ├── scan_service.py        # Nmap/OpenVAS/Metasploit scanning (~3100 lines)
│   │       ├── ioc_scan_service.py    # LOKI-RS IOC scanning via temp K8s pods (~550 lines)
│   │       ├── faraday_client.py      # Faraday REST API integration (~430 lines)
│   │       ├── config_service.py      # Terraform/Talos config file management
│   │       ├── kubectl_utils.py       # KubernetesHelper wrapper (~380 lines)
│   │       ├── process_manager.py     # Async subprocess execution + cancellation
│   │       └── base_service.py        # Shared mixin (logging, connectivity, poll_until)
│   ├── templates/            # Jinja2 (base, login, dashboard, deployment, config, scan, ioc_scan, logs)
│   ├── static/
│   │   ├── js/app.js         # authFetch(), getToken(), logout(), formatDuration/Timestamp()
│   │   ├── js/utils.js       # Additional formatting helpers
│   │   ├── js/websocket-base.js  # WebSocketBase class (WS + REST polling, see below)
│   │   ├── js/websocket.js   # Deployment-specific WS handler
│   │   ├── js/deployment.js  # deploymentMonitor() Alpine component
│   │   ├── js/scan.js        # scanManager() Alpine component
│   │   ├── js/ioc_scan.js    # iocScanManager() Alpine component
│   │   └── css/custom.css    # Dark theme Tailwind overrides
│   ├── deploy-lxc.sh         # LXC container provisioning
│   ├── Dockerfile            # Python 3.11 + terraform + talosctl + kubectl + helm + sops
│   └── requirements.txt
│
├── apps/                     # ArgoCD-managed K8s applications
│   ├── argocd/               # Self-managing (Helm 9.4.3, HA 2x replicas)
│   ├── metallb/              # L2 LB (0.15.3), IP pool 10.83.3.200-250, sync-wave: -2
│   ├── cert-manager/         # TLS (1.19.3), Cloudflare DNS-01, sync-wave: -1
│   ├── traefik/              # Ingress (38.0.2), fixed LB IP .200, sync-wave: 0
│   ├── ceph-storage/         # Ceph CSI RBD (3.13.0), StorageClass: ceph-rbd, sync-wave: 0
│   ├── metrics-server/       # HPA (3.13.0), --kubelet-insecure-tls, sync-wave: -2
│   ├── openvas/              # Greenbone (raw manifests), 11 init + 6 main containers, 10 PVCs
│   ├── faraday/              # Vuln mgmt (5.8.0), PostgreSQL + Redis + server
│   ├── metasploit/           # Pentest (raw manifests), privileged namespace
│   ├── harbor/               # Registry (bitnami 1.16.2), Trivy, Ceph storage, Recreate strategy
│   ├── threat-dragon/        # OWASP threat modeling
│   ├── securecodebox/        # Automated scanning framework (5.5.0)
│   ├── loki/                 # LOKI-RS IOC scanner image + build-and-push.sh
│   ├── network-policies/     # Zero-trust: default-deny per namespace
│   └── deploy-ingress-stack.sh  # 13-step infra deployment orchestrator
│
├── cluster/                  # Talos Linux configuration
│   ├── talconfig.yaml        # Cluster definition (Talos v1.12.2, K8s v1.32.3)
│   ├── talenv.yaml           # Env vars (node names, IPs, MACs) — substituted into talconfig
│   ├── talsecret.sops.yaml   # SOPS-encrypted cluster secrets
│   ├── apply-configs.sh      # DHCP IP discovery from Proxmox + config application
│   └── clusterconfig/        # Generated machine configs (gitignored)
│
├── terraform/
│   ├── cluster-create/       # Proxmox VMs via bpg/proxmox provider
│   ├── webui-lxc/            # WebUI LXC via shared module
│   ├── build-lxc/            # Build VM LXC via shared module
│   └── modules/proxmox-lxc/  # Reusable LXC module
│
├── scripts/                  # CLI orchestration
│   ├── DeployCluster.sh      # Full CLI deployment (alternative to WebUI)
│   ├── generate-secrets.sh   # SOPS/Age secret generation
│   └── tfvars-to-talos-env.sh # Terraform → talenv.yaml conversion
│
├── lib/                      # Shared bash utilities
│   ├── functions.sh          # Logging, wait_for_deployment/daemonset, retry_command
│   └── lxc-deploy-common.sh  # SSH key resolution, Windows path conversion
│
├── build-vm/                 # Docker image build LXC (VMID 201)
│   ├── deploy-lxc.sh
│   └── scripts/setup-lxc.sh  # Docker CE + kubectl install
│
└── docs/
    ├── DNS-MAPPING.md
    └── vuln-management-plan.md  # Next-phase plan (app split into 3 services)
```

---

## WebUI Application — Deep Dive

### Tech Stack
- **Backend:** FastAPI 0.109 + Uvicorn (async)
- **Frontend:** Jinja2 + Alpine.js 3.x + Tailwind CSS 3.x (CDN)
- **Auth:** JWT HS256 (8hr expiry) in HttpOnly cookie `access_token` + `Authorization: Bearer` header
- **Real-time:** WebSocket per feature + REST polling fallback via `WebSocketBase`
- **State:** Fernet-encrypted JSON files at `/app/data/` (no database)
- **Default credentials:** admin / admin (bcrypt hash in `config.py`)

### Application Wiring (main.py)

```python
# Router mounts — these define ALL API prefixes
app.include_router(auth.router,       prefix="/api/auth")
app.include_router(deployment.router, prefix="/api/deployment")
app.include_router(config.router,     prefix="/api/config")
app.include_router(scan.router,       prefix="/api/scan")
app.include_router(ioc_scan.router,   prefix="/api/ioc-scan")
app.include_router(websocket.router)  # mounts WS at /ws/deployment directly

# Page routes — each checks get_current_user_optional(), redirects to /login if None
GET /           → dashboard.html   (page="dashboard")
GET /login      → login.html
GET /config     → config.html      (page="config")
GET /deployment → deployment.html   (page="deployment")
GET /scan       → scan.html        (page="scan")
GET /ioc-scan   → ioc_scan.html    (page="ioc_scan")
GET /logs       → logs.html        (page="logs")

# System endpoints (no auth required)
GET /api/system/health        → {"status": "healthy"}
GET /api/system/dependencies  → checks shutil.which() for each tool
```

### Service Singleton Pattern

All three services use the same pattern:

```python
# Module-level singleton
_scan_service: Optional[ScanService] = None

def get_scan_service() -> ScanService:
    global _scan_service
    if _scan_service is None:
        _scan_service = ScanService()
    return _scan_service

# Injected into routers as FastAPI dependency
@router.post("/start")
async def start_scan(request: ScanRequest, service: ScanService = Depends(get_scan_service)):
```

### Service Inheritance

```
BaseServiceMixin              # Shared: _log_with_callback(), check_cluster_connectivity(),
    │                         #   poll_until(), @property k8s -> KubernetesHelper
    ├── DeploymentService     # @dataclass, ProcessManager, credentials dict, _save/_load_state()
    ├── ScanService           # @dataclass, ProcessManager, scan_history list
    └── IocScanService        # @dataclass, ProcessManager, scan_history list
```

Each service uses:
- `ProcessManager` for async subprocess calls (run_command with output streaming, cancellation)
- `KubernetesHelper` for kubectl operations (exec, pods, secrets, logs, namespaces)
- Callbacks (`log_callback`, `step_callback`/`tool_callback`/`status_callback`) for real-time broadcasting

### WebSocket Protocol

**Server → Client message format** (all features):
```json
{
  "type": "<message_type>",
  "timestamp": "2024-01-01T12:00:00.000000",
  "data": { ... }
}
```

**Message types by feature:**

| Feature | Type | Data Fields |
|---------|------|------------|
| Deployment | `initial_state` | id, status, current_step, steps[], logs[] |
| Deployment | `log` | step_id, level, message, timestamp |
| Deployment | `step_update` | step_id, name, description, status, started_at, completed_at, error_message |
| Deployment | `started` | {} |
| Deployment | `aborted` | {} |
| Scan | `scan_log` | tool, level, message, timestamp |
| Scan | `scan_tool_update` | tool, status, started_at, completed_at, error_message, findings_count, uploaded_to_faraday |
| IOC Scan | `ioc_log` | level, message, timestamp |
| IOC Scan | `ioc_status_update` | (full IocScanState dict) |

**Client → Server commands:** `{ "type": "ping" }` (all), `{ "type": "start" }` / `{ "type": "abort" }` (deployment WS only)

**Auth:** Via `?token=<jwt>` query param or `access_token` cookie. Rejected with close code `4001`.

### Frontend Component Pattern (Alpine.js + WebSocketBase)

Each page component follows this pattern:

```javascript
function scanManager() {
    return {
        // State fields
        status: 'idle', logs: [], ws: null, wsConnected: false, autoScroll: true,

        // Shared WebSocket/polling helper
        _wsBase: null,

        init() {
            this._wsBase = new WebSocketBase(
                '/api/scan/ws',      // WebSocket path
                '/api/scan/status',  // REST status poll URL
                '/api/scan/logs',    // REST logs poll URL (uses ?offset=N for pagination)
                { pollInterval: 3000, pingInterval: 15000 }
            );
            this._wsBase.bind(this);
            this._wsBase.connectWebSocket();
        },

        // REQUIRED by WebSocketBase:
        onWsMessage(message) { /* handle message.type dispatch */ },
        onPollStatus(data)   { /* update component state from REST poll */ },
        onPollComplete()     { /* called when polling detects run finished */ },
        // $refs.logContainer  (DOM element for auto-scroll target)
    };
}
```

**WebSocketBase** handles: WS connect/reconnect (auto-reconnect on non-normal close), heartbeat pings, REST polling fallback, log deduplication, buffer management (2000 max, trim to 1500), auto-scroll.

### Deployment Service — Steps & Timing

17 steps (0-16) defined in `DEPLOYMENT_STEPS[]` in `models/deployment.py`.

**Key timing constants** (in `deployment_service.py`):
- `VM_BOOT_INITIAL_DELAY = 180` — wait after Terraform apply
- `VM_READY_MAX_ATTEMPTS = 30`, `VM_READY_RETRY_INTERVAL = 10` — VM readiness polling
- `TALOS_API_CHECK_TIMEOUT = 15` — per-node API check
- State persisted to `/app/data/deployment_state.json` (Fernet-encrypted with SECRET_KEY)

**Step execution pattern:**
```python
async def _run_deployment(self):
    step_methods = [self._step_validate_git, self._step_check_dependencies, ...]
    for i, method in enumerate(step_methods):
        await self.update_step(i, StepStatus.RUNNING)
        success = await method(i)
        await self.update_step(i, StepStatus.SUCCESS if success else StepStatus.FAILED)
        if not success: break
```

### Scan Service — Tools & Profiles

**Timeouts (seconds):**
| Profile | Nmap | OpenVAS | Metasploit |
|---------|------|---------|------------|
| Quick | 300 | 7500 | 900 |
| Standard | 900 | 28800 | 5400 |
| Thorough | 3600 | 50400 | 10800 |

**Nmap flags:** Quick: `-T4 --top-ports 100`, Standard: `-sV -sC`, Thorough: `-sV -sC -p- -A`

**OpenVAS config UUIDs:** Quick: Host Discovery (`d21f6c81...`), Standard: Full and Fast (`daba56c8...`), Thorough: Full and Deep (`698f691e...`)

**Metasploit modules:** 11 for Standard (EternalBlue, Conficker, BlueKeep, Heartbleed, Log4Shell, Shellshock, HTTP.sys, SMB/SSH/HTTP/FTP version), 39 for Thorough (adds share/user enum, RDP, HTTP brute-force, DB scanners, etc.)

**Tool execution:** Each tool runs via `kubectl exec` or `kubectl run` against pods in K8s namespaces. Results are XML parsed locally, then uploaded to Faraday via individual REST calls.

### IOC Scan Service — LOKI-RS

1. Creates privileged pod in `loki-scanner` namespace (needs FUSE for SSHFS/CIFS)
2. Image: `harbor.knowledgeondemand.net/cleanroom/loki-rs-scanner:v2.10.0`
3. Mounts target via SSH or SMB, runs `loki -f /scan --no-procs --jsonl`
4. Parses JSONL output into `IocFinding[]` with severity: alert (≥80), warning (≥60), notice (<60)
5. Uploads to Faraday as host + vulns

---

## Settings (config.py)

```python
class Settings(BaseSettings):
    app_name: str = "Talos CleanRoom Deployment"
    debug: bool = False
    admin_username: str = "admin"
    admin_password_hash: str = "..."    # bcrypt hash of "admin"
    secret_key: str = "change-this..."  # JWT signing + Fernet state encryption
    access_token_expire_hours: int = 8
    repo_root: Path = Path("/repo")     # Git repo mount point in container
    master_node: str = "talos-CleanRoom-master-01.knowledgeondemand.net"
    health_check_retries: int = 30
    health_check_interval: int = 10
    node_ips: list[str] = ["10.83.3.10", "10.83.3.15", "10.83.3.16", "10.83.3.17"]
    dependencies: list[str] = ["terraform", "talhelper", "talosctl", "sops", "jq", "curl", "kubectl", "helm", "git"]
    class Config:
        env_file = ".env"
```

---

## ArgoCD & Sync Waves

**Deployment order** (sync-wave annotation):
- -2: metrics-server, MetalLB
- -1: cert-manager
- 0: Traefik (fixed LB IP 10.83.3.200), Ceph CSI
- 1: OpenVAS, Faraday, Harbor, Metasploit, Threat Dragon

All apps: `automated: { prune: true, selfHeal: true }`, ServerSideApply.
Secrets: SOPS-encrypted with Age, decrypted by ArgoCD KSOPS plugin.

---

## Infrastructure Details

### Ceph Storage
- 4 monitors at 10.83.2.20-23:6789
- Cluster ID: `1db975af-133e-43b1-9c6f-8e26269115f1`
- StorageClass: `ceph-rbd` (RWO, VirtIO block), used by OpenVAS (10 PVCs), Harbor (69Gi total), Faraday

### Talos Linux
- talconfig.yaml uses `${VAR}` placeholders substituted from talenv.yaml
- Factory schematic: `88d1f7a5...` (iscsi-tools, qemu-guest-agent, util-linux-tools)
- Kernel modules: nvme_tcp, vfio_pci, uio_pci_generic
- All nodes install to `/dev/vda`, DHCP on eth0

### Network Policies (Zero-Trust)
- Default deny all ingress+egress per namespace (faraday, threat-dragon, openvas, argocd)
- Metasploit: deny ingress only (egress unrestricted for pentesting)
- OpenVAS: egress DNS + HTTPS + rsync (feed sync)
- Traefik: allowed ingress source for all service namespaces

---

## Common Pitfalls

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| OpenVAS OOMKill at ~96% | ospd-openvas 1Gi limit | Set to 4Gi |
| Zombie processes in OpenVAS | Child process reaping | `shareProcessNamespace: true` |
| kubectl path mangling on Windows | MSYS converts `/bin/sh` | Use `//usr/local/bin/...` |
| Faraday bulk_create silent fail | No Celery worker in Community | Create hosts/services/vulns individually |
| Harbor perpetual OutOfSync | Auto-generated secrets change checksums | Ignore specific fields in ArgoCD |
| pg-gvm won't start | `args` replaces entrypoint CMD | Write conf.d/tuning.conf, use `start-postgresql` |
| kubectl exec large output truncated | SPDY chunk limit (200KB+) | Write to temp file, base64, retrieve |
| OpenVAS UDP scan bottleneck | nmap.nasl scans ~49K UDP ports | Port lists now profile-dependent |
| Python stdout buffering in kubectl | Non-TTY = full buffering | `python3 -u -c` + `flush=True` |

---

## Default Credentials

| Service | Username | Password | Notes |
|---------|----------|----------|-------|
| WebUI | admin | admin | JWT auth, configurable via .env |
| ArgoCD | admin | admin | bcrypt hash in values.yaml |
| Harbor | admin | Harbor12345 | Change on first login |
| OpenVAS | admin | admin | K8s secret `openvas-credentials` |
| Faraday | admin | (k8s secret) | Secret `faraday-credentials` |

---

## Planned Next Phase: App Split

See `docs/vuln-management-plan.md`. The monolithic WebUI splits into 3 apps:

1. **Deployment Console** (stays in LXC) — cluster lifecycle only, scan code removed
2. **Scanning Console** (new, in K8s) — scanning + PostgreSQL persistence + reports/export/remediation tracking
3. **Unified Portal** (new, in K8s) — landing page with shared JWT auth across all 3 apps

**New infrastructure:** `lib/talos-common/` shared pip package, `apps/scanning-console/`, `apps/portal/`, `apps/cleanroom-db/` (PostgreSQL)

**Migration:** Phases 1-4 additive (old WebUI untouched), Phases 5-8 cutover. Both old and new coexist during transition.

**Key design decisions in appendices:**
- **Appendix A:** Opaque one-time code exchange for cross-domain auth (no JWT in URL, single-use, per-user rate limited)
- **Appendix B:** Alembic migrations via hardened init container (non-root, read-only FS)
- **Appendix C:** Daily PostgreSQL backup CronJob with 14-day retention (PGPASSFILE, not PGPASSWORD)
- **Appendix D:** Faraday sync retry queue with exponential backoff
- **Appendix E:** PostgreSQL health probes (`pg_isready`)
- **Appendix F:** Build VM soft-failure pattern (Harbor auth check, skip if images exist)
- **Appendix G:** Portal stays FastAPI (needs JWT signing), kept minimal
- **Appendix H:** In-memory rate limiting accepted risk, Redis upgrade path documented
- **Appendix I:** Cryptographic key separation — derived keys for JWT/HMAC/Fernet from single SECRET_KEY
- **Appendix J:** Security checklist cross-referencing all 12 identified concerns and resolutions

---

## Conventions

- Shell scripts source `lib/functions.sh` for logging/wait helpers
- LXC deploys source `lib/lxc-deploy-common.sh` for SSH key resolution
- Each ArgoCD app has `application.yaml` + manifests or Helm values
- Secrets always SOPS-encrypted with Age
- Harbor images: `harbor.knowledgeondemand.net/cleanroom/<name>:<version>`
- Build scripts follow `apps/loki/build-and-push.sh` pattern
- Scan XML report format UUID: `a994b278-1f62-11e1-96ac-406186ea4fc5`
