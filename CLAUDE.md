# Claude Code Primer — Talos CleanRoom

> **Purpose:** Bring Claude up to speed at the start of every thread. Read this before making changes.
> Auto-memory at `~/.claude/projects/.../memory/MEMORY.md` has additional lessons learned.

## What This Project Is

A complete Infrastructure-as-Code platform for deploying a Talos Kubernetes cluster on Proxmox, with an integrated security toolchain (OpenVAS, Metasploit, Faraday, LOKI-RS IOC scanner). The platform is split into three web applications: a **Deployment Console** (cluster lifecycle, runs in LXC), a **Scanning Console** (vulnerability/IOC scanning with PostgreSQL persistence, runs in K8s), and a **Unified Portal** (landing page with cross-app SSO, runs in K8s). Everything is GitOps-managed via ArgoCD.

> **Deployment guide:** See `DEPLOYMENT.md` for end-to-end deployment instructions.

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
  │     ├── MetalLB IP Pool: 10.83.3.200-250 (L2 mode)
  │     ├── Scanning Console (scan.knowledgeondemand.net) — K8s Deployment
  │     ├── Portal (cleanroom.knowledgeondemand.net) — K8s Deployment
  │     └── CleanRoom DB — PostgreSQL 17 StatefulSet
  │
  ├── LXC: deployment-webui (VMID 200, 10.83.3.190) — Deployment Console
  └── LXC: build-vm (VMID 201, 10.83.3.191) — Docker image builds
```

**Ingress path:** Internet → MetalLB (10.83.3.200) → Traefik → K8s Services
**DNS:** All services at `*.knowledgeondemand.net` resolve to Traefik LB IP
**TLS:** Wildcard cert via cert-manager + Cloudflare DNS-01

---

## Repository Structure

```
Talos-CleanRoom/
├── webui/                    # Deployment Console — cluster lifecycle only (runs in LXC)
│   ├── app/
│   │   ├── main.py           # FastAPI app — mounts routers, static, templates, page routes
│   │   ├── auth.py           # JWT (HS256, 8hr) + bcrypt, HttpOnly cookies + Bearer header
│   │   ├── config.py         # Pydantic BaseSettings, @lru_cache singleton
│   │   ├── models/
│   │   │   ├── common.py     # BaseStatus enum, BaseLogEntry
│   │   │   ├── deployment.py # DeploymentState, DeploymentStep, StepStatus, DEPLOYMENT_STEPS[]
│   │   │   └── config.py     # NodeConfig, NetworkConfig, TerraformConfig
│   │   ├── routers/
│   │   │   ├── auth.py       # POST /api/auth/login, /logout, GET /me, POST /redeem-code
│   │   │   ├── deployment.py # POST start/abort, GET status/logs/kubeconfig/credentials, POST cleanup
│   │   │   ├── config.py     # GET/PUT terraform, GET talos/env, talos/config, all, validate
│   │   │   ├── websocket.py  # WS /ws/deployment (deployment real-time updates)
│   │   │   └── ws_manager.py # ConnectionManager (Set[WebSocket] + broadcast), create_message()
│   │   └── services/
│   │       ├── deployment_service.py  # 17-step cluster orchestrator (~1660 lines)
│   │       ├── config_service.py      # Terraform/Talos config file management
│   │       ├── kubectl_utils.py       # KubernetesHelper wrapper (~380 lines)
│   │       ├── process_manager.py     # Async subprocess execution + cancellation
│   │       └── base_service.py        # Shared mixin (logging, connectivity, poll_until)
│   ├── templates/            # Jinja2 (base, login, dashboard, deployment, config, logs)
│   ├── static/
│   │   ├── js/app.js         # authFetch(), getToken(), logout(), formatDuration/Timestamp()
│   │   ├── js/utils.js       # Additional formatting helpers
│   │   ├── js/websocket-base.js  # WebSocketBase class (WS + REST polling)
│   │   ├── js/websocket.js   # Deployment-specific WS handler
│   │   ├── js/deployment.js  # deploymentMonitor() Alpine component
│   │   └── css/custom.css    # Dark theme Tailwind overrides
│   ├── deploy-lxc.sh         # LXC container provisioning
│   ├── Dockerfile            # Python 3.11 + terraform + talosctl + kubectl + helm + sops
│   └── requirements.txt
│
├── scanning-app/             # Scanning Console — vulnerability/IOC scanning (runs in K8s)
│   ├── app/
│   │   ├── main.py           # FastAPI app — scan, IOC, reports, export routers
│   │   ├── config.py         # Inherits from talos_common ConfigBase
│   │   ├── models/
│   │   │   ├── scan.py       # ScanState, ScanTool, ScanProfile, ScanToolState, ScanRequest
│   │   │   └── ioc_scan.py   # IocScanState, MountType, IocFinding, IocScanRequest
│   │   ├── routers/
│   │   │   ├── scan.py       # POST start/abort, GET status/history/modules/openvas-*/logs, WS ws
│   │   │   ├── ioc_scan.py   # POST start/abort, GET status/history/logs, WS ws
│   │   │   ├── reports.py    # GET reports, scan detail, hosts, vulns, audit, compare
│   │   │   └── export.py     # GET CSV/JSON/PDF export, compliance reports
│   │   ├── services/
│   │   │   ├── scan_service.py        # Nmap/OpenVAS/Metasploit scanning (~3100 lines)
│   │   │   ├── ioc_scan_service.py    # LOKI-RS IOC scanning via temp K8s pods (~550 lines)
│   │   │   ├── faraday_client.py      # Faraday REST API integration (~430 lines)
│   │   │   ├── result_store.py        # PostgreSQL persistence for scan results
│   │   │   └── audit.py               # Audit logging
│   │   ├── db/
│   │   │   ├── engine.py     # SQLAlchemy async engine + session factory
│   │   │   ├── models.py     # ORM: Scan, Host, Vulnerability, IocFinding, FaradaySyncLog, AuditLog
│   │   │   └── repository.py # Data access layer
│   │   └── middleware/
│   │       ├── security.py   # SecurityHeadersMiddleware
│   │       └── rate_limit.py # RateLimitMiddleware
│   ├── alembic/              # Database migrations
│   │   └── versions/001_initial_schema.py
│   ├── templates/            # Jinja2 (scan, ioc_scan, reports suite)
│   ├── static/               # JS (scan, ioc_scan, reports) + CSS
│   ├── Dockerfile
│   └── requirements.txt
│
├── portal/                   # Unified Portal — landing page + cross-app SSO (runs in K8s)
│   ├── app/
│   │   ├── main.py           # FastAPI app — auth + portal routers
│   │   ├── config.py         # Inherits from talos_common ConfigBase
│   │   └── routers/
│   │       └── portal.py     # App links, status, navigation
│   ├── templates/            # Jinja2 (login, landing)
│   ├── Dockerfile
│   └── requirements.txt
│
├── lib/                      # Shared utilities
│   ├── talos-common/         # Shared pip package (talos_common) used by all 3 apps
│   │   └── talos_common/
│   │       ├── auth.py       # JWT decode, get_current_user_optional
│   │       ├── config_base.py # Pydantic BaseSettings mixin + key derivation
│   │       ├── models/common.py # Shared Pydantic models
│   │       ├── routers/
│   │       │   ├── auth.py       # Shared login/logout/me endpoints
│   │       │   ├── exchange.py   # Cross-domain one-time code exchange
│   │       │   └── ws_manager.py # Shared WebSocket ConnectionManager
│   │       └── services/
│   │           ├── base_service.py    # Logging, kubectl, poll_until
│   │           ├── kubectl_utils.py   # KubernetesHelper wrapper
│   │           └── process_manager.py # Async subprocess execution
│   ├── functions.sh          # Logging, wait_for_deployment/daemonset, retry_command
│   └── lxc-deploy-common.sh  # SSH key resolution, Windows path conversion
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
│   ├── scanning-console/     # K8s manifests for Scanning Console (Deployment, Service, RBAC, IngressRoute)
│   ├── portal/               # K8s manifests for Portal (Deployment, Service, IngressRoute)
│   ├── cleanroom-db/         # PostgreSQL 17 StatefulSet + backup CronJob + PVCs
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
├── build-vm/                 # Docker image build LXC (VMID 201)
│   ├── deploy-lxc.sh
│   └── scripts/setup-lxc.sh  # Docker CE + kubectl install
│
├── DEPLOYMENT.md             # End-to-end deployment guide (16 steps)
└── docs/
    ├── DNS-MAPPING.md
    └── vuln-management-plan.md  # Architecture plan (implemented, Phases 1-8 complete)
```

---

## Application Architecture (3-App Split)

All three apps share `lib/talos-common/` (pip package `talos_common`) for auth, config, WebSocket management, and kubectl utilities.

### Shared Tech Stack
- **Backend:** FastAPI 0.109 + Uvicorn (async)
- **Frontend:** Jinja2 + Alpine.js 3.x + Tailwind CSS 3.x (CDN)
- **Auth:** JWT HS256 (8hr expiry) in HttpOnly cookie + Bearer header, cross-app SSO via opaque one-time codes
- **Real-time:** WebSocket per feature + REST polling fallback via `WebSocketBase`
- **Key derivation:** Single `SECRET_KEY` → derived `jwt_signing_key`, `code_exchange_key`, `fernet_key`
- **Default credentials:** admin / admin (all three apps)

### Deployment Console (webui/) — Cluster Lifecycle

Runs in LXC container (VMID 200, 10.83.3.190:8000). State: Fernet-encrypted JSON files (no database).

```python
# Router mounts (webui/app/main.py)
app.include_router(auth.router,       prefix="/api/auth")       # login/logout/me/redeem-code
app.include_router(exchange_router,   prefix="/api/auth")       # cross-domain code exchange
app.include_router(deployment.router, prefix="/api/deployment")
app.include_router(config.router,     prefix="/api/config")
app.include_router(websocket.router)  # WS /ws/deployment

# Pages: /, /login, /config, /deployment, /logs
# System: GET /api/system/health, /api/system/dependencies
```

### Scanning Console (scanning-app/) — Vulnerability & IOC Scanning

Runs in K8s (namespace `scanning-console`, image from Harbor). Uses PostgreSQL via `cleanroom-db`.

```python
# Router mounts (scanning-app/app/main.py)
app.include_router(auth_router,       prefix="/api/auth")       # shared from talos_common
app.include_router(exchange_router,   prefix="/api/auth")       # cross-domain code exchange
app.include_router(scan.router,       prefix="/api/scan")
app.include_router(ioc_scan.router,   prefix="/api/ioc-scan")
app.include_router(reports.router,    prefix="/api/reports")
app.include_router(export.router,     prefix="/api/export")

# Pages: /scan, /ioc-scan, /reports, /login
# Database: SQLAlchemy async + Alembic migrations (init container)
# Middleware: SecurityHeadersMiddleware, RateLimitMiddleware
# CORS: allows portal + deployment console origins
```

**Database schema** (scanning-app/app/db/models.py): Scan, Host, Vulnerability, IocFinding, FaradaySyncLog, AuditLog

### Portal (portal/) — Landing Page + SSO

Runs in K8s (namespace `portal`, image from Harbor). Minimal app — auth + navigation links.

```python
# Router mounts (portal/app/main.py)
app.include_router(auth_router,       prefix="/api/auth")       # shared from talos_common
app.include_router(portal.router,     prefix="/api/portal")     # app links, status

# Pages: / (landing), /login
```

### Cross-Domain Auth Flow

Portal generates HMAC-signed one-time codes → target app redeems via `POST /api/auth/redeem-code` → mints local JWT. No JWT in URL, single-use, per-user rate limited. See `lib/talos-common/talos_common/routers/exchange.py`.

### Service Inheritance (shared via talos_common)

```
talos_common.services.BaseServiceMixin   # _log_with_callback(), check_cluster_connectivity(),
    │                                    #   poll_until(), @property k8s -> KubernetesHelper
    │
    ├── webui: DeploymentService         # 17-step cluster orchestrator, Fernet state
    ├── scanning-app: ScanService        # Nmap/OpenVAS/Metasploit, PostgreSQL persistence
    └── scanning-app: IocScanService     # LOKI-RS IOC scanning, PostgreSQL persistence
```

### WebSocket Protocol

**Server → Client message format** (all apps):
```json
{
  "type": "<message_type>",
  "timestamp": "2024-01-01T12:00:00.000000",
  "data": { ... }
}
```

**Message types by app:**

| App | Type | Data Fields |
|-----|------|------------|
| Deployment Console | `initial_state` | id, status, current_step, steps[], logs[] |
| Deployment Console | `log` | step_id, level, message, timestamp |
| Deployment Console | `step_update` | step_id, name, description, status, started_at, completed_at, error_message |
| Deployment Console | `started` / `aborted` | {} |
| Scanning Console | `scan_log` | tool, level, message, timestamp |
| Scanning Console | `scan_tool_update` | tool, status, started_at, completed_at, error_message, findings_count, uploaded_to_faraday |
| Scanning Console | `ioc_log` | level, message, timestamp |
| Scanning Console | `ioc_status_update` | (full IocScanState dict) |

**Client → Server:** `{ "type": "ping" }` (all), `{ "type": "start" }` / `{ "type": "abort" }` (deployment WS only)

**Auth:** Via `?token=<jwt>` query param or `access_token` cookie. Rejected with close code `4001`.

### Frontend Component Pattern (Alpine.js + WebSocketBase)

Each page component follows this pattern (example from scanning-app):

```javascript
function deploymentMonitor() {
    return {
        status: 'idle', logs: [], ws: null, wsConnected: false, autoScroll: true,
        _wsBase: null,
        init() {
            this._wsBase = new WebSocketBase(
                '/ws/deployment',              // WebSocket path
                '/api/deployment/status',      // REST status poll URL
                '/api/deployment/logs',        // REST logs poll URL (?offset=N)
                { pollInterval: 3000, pingInterval: 15000 }
            );
            this._wsBase.bind(this);
            this._wsBase.connectWebSocket();
        },
        // REQUIRED: onWsMessage(msg), onPollStatus(data), onPollComplete()
    };
}
```

**WebSocketBase** handles: WS connect/reconnect, heartbeat pings, REST polling fallback, log deduplication, buffer management (2000 max, trim to 1500), auto-scroll.

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

### Scan Service — Tools & Profiles (scanning-app)

Located in `scanning-app/app/services/scan_service.py`. Results persisted to PostgreSQL via `result_store.py`.

**Timeouts (seconds):**
| Profile | Nmap | OpenVAS | Metasploit |
|---------|------|---------|------------|
| Quick | 300 | 7500 | 900 |
| Standard | 900 | 28800 | 5400 |
| Thorough | 3600 | 50400 | 10800 |

**Nmap flags:** Quick: `-T4 --top-ports 100`, Standard: `-sV -sC`, Thorough: `-sV -sC -p- -A`

**OpenVAS config UUIDs:** Quick: Host Discovery (`d21f6c81...`), Standard: Full and Fast (`daba56c8...`), Thorough: Full and Deep (`698f691e...`)

**Metasploit modules:** 11 for Standard (EternalBlue, Conficker, BlueKeep, Heartbleed, Log4Shell, Shellshock, HTTP.sys, SMB/SSH/HTTP/FTP version), 39 for Thorough (adds share/user enum, RDP, HTTP brute-force, DB scanners, etc.)

**Tool execution:** Each tool runs via `kubectl exec` or `kubectl run` against pods in K8s namespaces. Results are XML parsed locally, persisted to PostgreSQL, then uploaded to Faraday via individual REST calls.

### IOC Scan Service — LOKI-RS (scanning-app)

Located in `scanning-app/app/services/ioc_scan_service.py`.

1. Creates privileged pod in `loki-scanner` namespace (needs FUSE for SSHFS/CIFS)
2. Image: `harbor.knowledgeondemand.net/cleanroom/loki-rs-scanner:v2.10.0`
3. Mounts target via SSH or SMB, runs `loki -f /scan --no-procs --jsonl`
4. Parses JSONL output into `IocFinding[]` with severity: alert (≥80), warning (≥60), notice (<60)
5. Persists findings to PostgreSQL + uploads to Faraday as host + vulns

---

## Settings

All three apps inherit from `talos_common.ConfigBase` which provides shared fields (`secret_key`, `admin_username`, `admin_password_hash`, `access_token_expire_hours`). Key derivation happens in ConfigBase: `jwt_signing_key`, `code_exchange_key`, `fernet_key` are derived from the single `SECRET_KEY`.

### Deployment Console (webui/app/config.py)

```python
class Settings(ConfigBase):
    app_name: str = "Talos CleanRoom Deployment"
    repo_root: Path = Path("/repo")
    master_node: str = "talos-CleanRoom-master-01.knowledgeondemand.net"
    node_ips: list[str] = ["10.83.3.10", "10.83.3.15", "10.83.3.16", "10.83.3.17"]
    dependencies: list[str] = ["terraform", "talhelper", "talosctl", "sops", "jq", "curl", "kubectl", "helm", "git"]
```

### Scanning Console (scanning-app/app/config.py)

```python
class Settings(ConfigBase):
    app_name: str = "Talos CleanRoom Scanning Console"
    database_url: str = "postgresql+asyncpg://cleanroom:password@cleanroom-db.cleanroom-db.svc:5432/cleanroom"
```

### Portal (portal/app/config.py)

```python
class Settings(ConfigBase):
    app_name: str = "Talos CleanRoom Portal"
    deployment_console_url: str = "https://10.83.3.190:8000"
    scanning_console_url: str = "https://scan.knowledgeondemand.net"
```

**Critical:** All three apps must share the same `SECRET_KEY` for cross-domain SSO to work.

---

## ArgoCD & Sync Waves

**Deployment order** (sync-wave annotation):
- -2: metrics-server, MetalLB
- -1: cert-manager
- 0: Traefik (fixed LB IP 10.83.3.200), Ceph CSI
- 1: OpenVAS, Faraday, Harbor, Metasploit, Threat Dragon, CleanRoom DB, Scanning Console, Portal

All apps: `automated: { prune: true, selfHeal: true }`, ServerSideApply.
Secrets: SOPS-encrypted with Age, decrypted by ArgoCD KSOPS plugin.

---

## Infrastructure Details

### Ceph Storage
- 4 monitors at 10.83.2.20-23:6789
- Cluster ID: `1db975af-133e-43b1-9c6f-8e26269115f1`
- StorageClass: `ceph-rbd` (RWO, VirtIO block), used by OpenVAS (10 PVCs), Harbor (69Gi total), Faraday, CleanRoom DB

### Talos Linux
- talconfig.yaml uses `${VAR}` placeholders substituted from talenv.yaml
- Factory schematic: `88d1f7a5...` (iscsi-tools, qemu-guest-agent, util-linux-tools)
- Kernel modules: nvme_tcp, vfio_pci, uio_pci_generic
- All nodes install to `/dev/vda`, DHCP on eth0

### Network Policies (Zero-Trust)
- Default deny all ingress+egress per namespace (faraday, threat-dragon, openvas, argocd, scanning-console, portal, cleanroom-db)
- Metasploit: deny ingress only (egress unrestricted for pentesting)
- OpenVAS: egress DNS + HTTPS + rsync (feed sync)
- Scanning Console: egress to cleanroom-db, openvas, faraday, metasploit, loki-scanner, nmap-scanner, K8s API, DNS
- CleanRoom DB: ingress from scanning-console only, egress DNS only
- Portal: egress DNS only
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
| Deployment Console | admin | admin | JWT auth, configurable via .env |
| Scanning Console | admin | admin | K8s secret `scanning-console-credentials` |
| Portal | admin | admin | K8s secret `portal-credentials` |
| ArgoCD | admin | admin | bcrypt hash in values.yaml |
| Harbor | admin | Harbor12345 | Change on first login |
| OpenVAS | admin | admin | K8s secret `openvas-credentials` |
| Faraday | admin | (k8s secret) | Secret `faraday-credentials` |

---

## App Split — Design Decisions

The 3-app split is **implemented** (Phases 1-8 complete on `refactor/restructure`). See `docs/vuln-management-plan.md` for the full architecture plan and appendices.

**Key design decisions:**
- **Cross-domain auth:** Opaque one-time HMAC-signed code exchange (no JWT in URL, single-use, per-user rate limited) — Appendix A
- **Database migrations:** Alembic via hardened init container (non-root, read-only FS) — Appendix B
- **Backups:** Daily pg_dump CronJob with 14-day retention, PGPASSFILE (not PGPASSWORD) — Appendix C
- **Faraday sync:** Retry queue with exponential backoff — Appendix D
- **Key separation:** Derived keys for JWT/HMAC/Fernet from single SECRET_KEY — Appendix I
- **Security:** 12-concern checklist with resolutions — Appendix J

---

## Conventions

- Shell scripts source `lib/functions.sh` for logging/wait helpers
- LXC deploys source `lib/lxc-deploy-common.sh` for SSH key resolution
- All three FastAPI apps import shared auth/services from `lib/talos-common/` (`talos_common` package)
- Each ArgoCD app has `application.yaml` + manifests or Helm values
- Secrets always SOPS-encrypted with Age
- Harbor images: `harbor.knowledgeondemand.net/cleanroom/<name>:<version>`
- Build scripts follow `apps/loki/build-and-push.sh` pattern
- Scan XML report format UUID: `a994b278-1f62-11e1-96ac-406186ea4fc5`
- End-to-end deployment: see `DEPLOYMENT.md` at repo root
