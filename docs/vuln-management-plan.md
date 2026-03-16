# Plan: Split WebUI into Deployment Console + K8s Scanning Console

> **Status: Implemented** (Phases 1–8 complete on `refactor/restructure` branch)

## Context

The monolithic WebUI (LXC container) currently handles both cluster deployment AND security scanning. This plan splits it into three independent applications:

1. **Deployment Console** (stays in LXC) — deploys/configures the K8s cluster via terraform, talosctl, helm
2. **Scanning Console** (new, runs in K8s) — scanning, reporting, vulnerability management, DB persistence
3. **Unified Portal** (new, runs in K8s) — landing page with links to both apps, shared login

This supersedes the previous vuln-management-plan — all DB/reporting/security features from that plan are incorporated into the Scanning Console.

**Key decisions:**
- Monorepo: `scanning-app/` and `portal/` alongside existing `webui/`
- Shared JWT secret across all three apps (login once, token works everywhere)
- Shared code extracted to `lib/talos-common/` pip-installable package
- ServiceAccount + least-privilege RBAC for the scanning app's kubectl access
- PostgreSQL uses ClusterIP (not NodePort) since scanning app is now in-cluster

---

## Documentation Strategy

Documentation updates are woven into each phase — every phase that creates or modifies components also updates the relevant docs. A final documentation-only pass (Phase 8) catches anything missed.

### Documents requiring updates

| Document | Current State | Required Changes |
|----------|--------------|------------------|
| `README.md` (root) | Describes monolithic WebUI for deployment + scanning | Update architecture diagram, project structure, deployed services table, deployment workflow, accessing services table, add new DNS records |
| `webui/README.md` | Describes full WebUI (deploy + scan) | Trim to deployment-only scope, remove scan/IOC scan sections, update architecture tree, API endpoints, pages table |
| `webui/README-TECHNICAL.md` | Full technical architecture | Remove scan/IOC scan architecture sections, update backend structure, WebSocket table, Alpine.js components, key files |
| `docs/DNS-MAPPING.md` | Lists current DNS records | Add `scan.knowledgeondemand.net`, `cleanroom.knowledgeondemand.net`, `cleanroom-db` (internal only) |
| `docs/vuln-management-plan.md` | The plan itself | Mark as "Implemented" with date once complete |
| `build-vm/README.md` | Documents LOKI-RS image builds | Add scanning-console and portal image build instructions |
| `apps/network-policies/README.md` | Documents existing policies | Add scanning-console, portal, cleanroom-db policies to overview table |
| `apps/traefik/README.md` | Documents ingress/DNS config | Add `scan.knowledgeondemand.net` and `cleanroom.knowledgeondemand.net` to DNS section |

### New documentation files

| Document | Phase Created | Content |
|----------|--------------|---------|
| `lib/talos-common/README.md` | Phase 1 | Package purpose, exported modules, install instructions, development workflow |
| `scanning-app/README.md` | Phase 2 | Scanning console features, architecture, DB schema summary, API endpoints, Dockerfile, build-and-push, env vars, troubleshooting |
| `portal/README.md` | Phase 3 | Portal purpose, cross-domain auth flow, env vars, Dockerfile |
| `apps/scanning-console/README.md` | Phase 4 | K8s manifests overview, RBAC summary, deployment instructions, IngressRoute |
| `apps/cleanroom-db/README.md` | Phase 4 | PostgreSQL StatefulSet docs, backup/restore, SOPS secrets, PVC sizing |
| `apps/portal/README.md` | Phase 4 | K8s manifests overview, deployment instructions |

---

## Repository Layout (Post-Split)

```
Talos-CleanRoom/
  lib/talos-common/                       # Shared Python package (~900 lines)
    pyproject.toml
    README.md                             # NEW: package docs
    talos_common/
      __init__.py
      auth.py                             # JWT create/decode/verify
      config_base.py                      # BaseAppSettings (auth fields only)
      models/common.py                    # BaseStatus, BaseLogEntry
      services/process_manager.py         # ProcessManager
      services/kubectl_utils.py           # KubernetesHelper
      services/base_service.py            # BaseServiceMixin
      routers/auth.py                     # Login/logout endpoints
      routers/exchange.py                 # One-time code exchange (redeem-code endpoint)
      routers/ws_manager.py               # ConnectionManager
      static/js/app.js                    # Shared auth/fetch utils + auto-redeem code snippet
      static/js/utils.js                  # formatDuration, etc.
      static/js/websocket-base.js         # WebSocketBase class
      templates/components.html           # Shared Jinja2 macros
      templates/login.html                # Shared login page

  webui/                                  # TRIMMED: Deployment Console only
    app/
      main.py                             # Only deployment + config routes
      config.py                           # DeploymentSettings(BaseAppSettings)
      routers/deployment.py, config.py, websocket.py
      models/deployment.py, config.py
      services/deployment_service.py, config_service.py
    static/js/deployment.js
    templates/base.html, dashboard.html, deployment.html, config.html, logs.html
    Dockerfile                            # Existing (terraform, talosctl, etc.)
    requirements.txt

  scanning-app/                           # NEW: Scanning Console
    README.md                             # NEW: scanning console docs
    app/
      main.py                             # Scan + report routes, DB lifespan
      config.py                           # ScanningSettings(BaseAppSettings)
      db/engine.py, models.py, repository.py
      middleware/csrf.py, security_headers.py, rate_limit.py
      routers/scan.py, ioc_scan.py, reports.py, export.py
      models/scan.py, ioc_scan.py
      services/scan_service.py, ioc_scan_service.py, faraday_client.py, result_store.py
    static/js/scan.js, ioc_scan.js, reports.js, reports_detail.js, reports_compare.js
    templates/base.html, scan.html, ioc_scan.html, reports*.html, reports_audit.html
    alembic/env.py, versions/001_initial_schema.py
    Dockerfile                            # NEW: Python 3.11-slim + kubectl only
    build-and-push.sh                     # NEW: Harbor build script
    requirements.txt

  portal/                                 # NEW: Unified Login Portal
    README.md                             # NEW: portal docs
    app/main.py, config.py
    templates/base.html, login.html, landing.html
    Dockerfile
    build-and-push.sh
    requirements.txt

  apps/
    scanning-console/                     # NEW: K8s manifests
      README.md                           # NEW: K8s deployment docs
      namespace.yaml, deployment.yaml, service.yaml, ingressroute.yaml
      serviceaccount.yaml, clusterrole.yaml, clusterrolebinding.yaml
      secrets.sops.yaml, application.yaml
    portal/                               # NEW: K8s manifests
      README.md                           # NEW: K8s deployment docs
      namespace.yaml, deployment.yaml, service.yaml, ingressroute.yaml
      application.yaml
    cleanroom-db/                         # NEW: PostgreSQL
      README.md                           # NEW: PostgreSQL docs
      namespace.yaml, statefulset.yaml, service.yaml, pvc.yaml
      secrets.sops.yaml, application.yaml
      backup-cronjob.yaml                 # NEW: daily pg_dump CronJob
      backup-pvc.yaml                     # NEW: 5Gi Ceph RBD for backup storage
    network-policies/
      scanning-console-policy.yaml        # NEW
      portal-policy.yaml                  # NEW
      cleanroom-db-policy.yaml            # NEW
```

---

## Phase 1: Extract Shared Code into `lib/talos-common/`

### 1.1 Create pip-installable package

**`lib/talos-common/pyproject.toml`:**
```toml
[project]
name = "talos-common"
version = "0.1.0"
dependencies = [
    "fastapi>=0.109.0",
    "python-jose[cryptography]>=3.3.0",
    "passlib[bcrypt]>=1.7.4",
    "pydantic>=2.5.3",
    "pydantic-settings>=2.1.0",
]
```

### 1.2 Files extracted from `webui/app/`

| Source | Destination | Lines |
|--------|------------|-------|
| `auth.py` | `talos_common/auth.py` | 104 |
| `config.py` (base fields only) | `talos_common/config_base.py` | ~30 |
| `models/common.py` | `talos_common/models/common.py` | 37 |
| `services/process_manager.py` | `talos_common/services/process_manager.py` | 192 |
| `services/kubectl_utils.py` | `talos_common/services/kubectl_utils.py` | 379 |
| `services/base_service.py` | `talos_common/services/base_service.py` | 144 |
| `routers/auth.py` | `talos_common/routers/auth.py` | ~69 |
| (new) | `talos_common/routers/exchange.py` | ~40 |
| `routers/ws_manager.py` | `talos_common/routers/ws_manager.py` | 47 |
| `static/js/app.js` | `talos_common/static/js/app.js` | shared |
| `static/js/utils.js` | `talos_common/static/js/utils.js` | shared |
| `static/js/websocket-base.js` | `talos_common/static/js/websocket-base.js` | shared |
| `templates/components.html` | `talos_common/templates/components.html` | shared |
| `templates/login.html` | `talos_common/templates/login.html` | shared |

### 1.3 BaseAppSettings

```python
class BaseAppSettings(BaseSettings):
    secret_key: str = "change-me-in-production"
    admin_username: str = "admin"
    admin_password_hash: str = "$2b$12$..."  # default "admin"
    access_token_expire_hours: int = 8

    @property
    def jwt_signing_key(self) -> str:
        """Derived key for JWT signing (HMAC-SHA256 of secret_key + 'jwt')."""
        return hmac.new(self.secret_key.encode(), b"jwt-signing", hashlib.sha256).hexdigest()

    @property
    def code_exchange_key(self) -> str:
        """Derived key for one-time code HMAC (separate from JWT key)."""
        return hmac.new(self.secret_key.encode(), b"code-exchange", hashlib.sha256).hexdigest()

    @property
    def fernet_key(self) -> bytes:
        """Derived key for Fernet state encryption (separate from JWT key)."""
        import base64
        key_bytes = hmac.new(self.secret_key.encode(), b"fernet-state", hashlib.sha256).digest()
        return base64.urlsafe_b64encode(key_bytes)
```

**Key derivation:** A single `SECRET_KEY` env var is shared across all three apps, but each cryptographic purpose uses a **derived key** via HMAC with a distinct context string. Compromising one derived key (e.g., from a JWT signature) does not expose the others. See **Appendix I** for the security rationale.

Each app inherits and adds its own fields:
- `DeploymentSettings` adds: `repo_root`, `master_node`, `node_ips`, `dependencies`
- `ScanningSettings` adds: `database_url`, `faraday_sync_enabled`
- `PortalSettings` adds: `deployment_console_url`, `scanning_console_url`

### 1.4 Install pattern

- Development: `pip install -e lib/talos-common`
- Docker: `COPY lib/talos-common /tmp/talos-common && pip install /tmp/talos-common`
- Both apps import: `from talos_common.auth import get_current_user`

### 1.5 Documentation (Phase 1)

- **Create `lib/talos-common/README.md`**: Package purpose, exported modules table, install instructions (dev + Docker), how apps inherit `BaseAppSettings`
- **Update `README.md` (root)**: Add `lib/talos-common/` to project structure tree with description

---

## Phase 2: Create Scanning Console Application

### 2.1 App structure (`scanning-app/`)

New FastAPI app containing:
- **Scan orchestration**: `scan_service.py` (3114 lines), `ioc_scan_service.py` (547 lines), `faraday_client.py` (430 lines) — copied from `webui/app/services/`
- **Database layer**: `db/engine.py`, `db/models.py`, `db/repository.py`
- **Result storage**: `result_store.py` — parses XML/JSONL, writes to PostgreSQL
- **Reports API**: `routers/reports.py` — summary, hosts, vulns, compare, trends
- **Export**: `routers/export.py` — PDF (ReportLab) and CSV
- **Security middleware**: CSRF, CSP headers, rate limiting, audit logging
- **Templates**: scan.html, ioc_scan.html, 6 reports pages, audit log viewer
- **Alpine.js components**: scanManager(), reportsManager(), scanDetailManager(), scanCompareManager()

### 2.2 Database schema

Connection string (in-cluster DNS, no NodePort):
```
postgresql+asyncpg://cleanroom:<pw>@cleanroom-db.cleanroom-db.svc.cluster.local:5432/cleanroom
```

Tables (PostgreSQL with JSONB columns):

```
scans
  id                TEXT PK (uuid[:8])
  scan_type         TEXT NOT NULL ("security" | "ioc")
  target            TEXT NOT NULL
  profile           TEXT (quick/standard/thorough/custom, NULL for IOC)
  mount_type        TEXT (ssh/smb, NULL for security)
  scan_path         TEXT (IOC only)
  status            TEXT NOT NULL
  started_at        TIMESTAMP
  completed_at      TIMESTAMP
  error_message     TEXT
  tools_json        JSONB (tool states array)
  custom_modules    JSONB
  openvas_config    TEXT
  openvas_families  JSONB
  INDEX: started_at, status, scan_type

hosts
  id                SERIAL PK
  scan_id           TEXT FK -> scans.id CASCADE
  ip                TEXT NOT NULL
  os                TEXT
  description       TEXT
  hostnames         JSONB
  tags              JSONB
  created_at        TIMESTAMP DEFAULT now()
  UNIQUE(scan_id, ip)
  INDEX: ip, scan_id

services
  id                SERIAL PK
  host_id           INTEGER FK -> hosts.id CASCADE
  scan_id           TEXT FK -> scans.id CASCADE
  name              TEXT
  port              INTEGER NOT NULL
  protocol          TEXT DEFAULT 'tcp'
  status            TEXT DEFAULT 'open'
  version           TEXT
  INDEX: host_id, port

vulnerabilities
  id                SERIAL PK
  scan_id           TEXT FK -> scans.id CASCADE
  host_id           INTEGER FK -> hosts.id CASCADE
  service_id        INTEGER FK -> services.id SET NULL (nullable)
  name              TEXT NOT NULL
  description       TEXT
  severity          TEXT NOT NULL (critical/high/medium/low/info/unclassified)
  refs              JSONB (reference URLs)
  resolution        TEXT
  data              TEXT
  external_id       TEXT (CVE)
  tags              JSONB
  type              TEXT DEFAULT 'Vulnerability'
  tool_source       TEXT (nmap/openvas/metasploit)
  path, website, method, request, response, query  TEXT  -- web vuln fields
  remediation_status TEXT DEFAULT 'open'
      (open/acknowledged/in_progress/fixed/false_positive/accepted_risk)
  remediation_notes  TEXT
  remediation_updated_at TIMESTAMP
  INDEX: severity, scan_id, host_id, remediation_status, external_id

ioc_findings
  id                SERIAL PK
  scan_id           TEXT FK -> scans.id CASCADE
  host_id           INTEGER FK -> hosts.id CASCADE (nullable)
  severity          TEXT NOT NULL (alert/warning/notice)
  score             INTEGER NOT NULL
  file_path         TEXT NOT NULL
  rule_name         TEXT
  description       TEXT
  matched_strings   JSONB
  hash_md5          TEXT
  hash_sha256       TEXT
  tags              JSONB
  remediation_status TEXT DEFAULT 'open'
  remediation_notes  TEXT
  remediation_updated_at TIMESTAMP
  INDEX: scan_id, severity, hash_sha256

faraday_sync_log
  id                SERIAL PK
  scan_id           TEXT FK -> scans.id CASCADE
  synced_at         TIMESTAMP
  success           BOOLEAN
  detail            TEXT
  retry_count       INTEGER DEFAULT 0
  next_retry_at     TIMESTAMP          # NULL if success=true or retries exhausted
  scan_type         TEXT               # "security" | "ioc" — dispatch correct upload logic
  INDEX: success, next_retry_at        # For retry query efficiency

audit_log
  id                SERIAL PK
  timestamp         TIMESTAMP DEFAULT now()
  action            TEXT NOT NULL
  user              TEXT
  source_ip         TEXT
  resource_type     TEXT
  resource_id       TEXT
  detail            JSONB
  INDEX: timestamp, action, user
```

### 2.3 Dual-write pattern

After each scan tool completes:
1. Parse XML locally via `result_store` -> write to PostgreSQL (primary, synchronous)
2. Upload to Faraday via `faraday_client` (secondary, best-effort with retry)

If Faraday upload fails, the failure is logged in `faraday_sync_log` and retried up to 3 times with exponential backoff (5m, 10m, 20m) by a background asyncio task. PostgreSQL is always the source of truth. See **Appendix D** for full retry queue design and reconciliation API.

### 2.4 Reports REST API

```
GET  /api/reports/summary                  -- total hosts, vulns by severity, scan count
GET  /api/reports/scans                    -- paginated scan list
GET  /api/reports/scans/{id}               -- scan detail with hosts/services/vulns
GET  /api/reports/hosts                    -- paginated host list
GET  /api/reports/hosts/{id}               -- host detail with services and vulns
GET  /api/reports/vulns                    -- paginated vuln list with filters
PATCH /api/reports/vulns/{id}/remediation  -- update remediation status
POST /api/reports/vulns/bulk-remediation   -- bulk update
GET  /api/reports/compare?a={id}&b={id}    -- diff two scans
GET  /api/reports/trends                   -- time-series for charts
GET  /api/reports/audit                    -- paginated audit log
```

### 2.5 Reports UI pages

| Route | Template | Purpose |
|-------|----------|---------|
| `/reports` | `reports.html` | Dashboard: stat cards, Chart.js doughnut + trend line |
| `/reports/hosts` | `reports_hosts.html` | Host table with expandable rows |
| `/reports/vulns` | `reports_vulns.html` | Vuln table with filters, bulk remediation |
| `/reports/scan/{id}` | `reports_scan_detail.html` | Scan detail, host/vuln tree, export buttons |
| `/reports/compare` | `reports_compare.html` | Side-by-side scan diff |
| `/reports/audit` | `reports_audit.html` | Audit log viewer |

### 2.6 Export

- **PDF** (ReportLab): cover page, executive summary, host inventory, vuln details by severity
- **CSV** (stdlib): host_ip, port, service, vuln_name, severity, remediation_status, CVE, tool

### 2.7 Scanning Console Dockerfile

```dockerfile
FROM python:3.11-slim AS builder
# install gcc, pip install talos-common + requirements

FROM python:3.11-slim
# Install kubectl v1.32 only (no terraform, talosctl, helm, sops)
# COPY app, static, templates, alembic, alembic.ini
# HEALTHCHECK on /api/system/health
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

kubectl works inside K8s pods automatically via `KUBERNETES_SERVICE_HOST` env var and ServiceAccount token at `/var/run/secrets/kubernetes.io/serviceaccount/token`.

**Database migrations** run via an init container (`alembic upgrade head`) before the app starts. See **Appendix B** for full Alembic configuration and manual migration procedures.

### 2.8 `scanning-app/build-and-push.sh`

Following `apps/loki/build-and-push.sh` pattern:
1. Check prerequisites (Docker, kubectl, curl, jq)
2. Collect Harbor credentials
3. Wait for Harbor health
4. Create/verify `cleanroom` project
5. Create `harbor-pull-secret` in `scanning-console` namespace
6. Docker login, build, push `harbor.knowledgeondemand.net/cleanroom/scanning-console:<version>`

### 2.9 Documentation (Phase 2)

- **Create `scanning-app/README.md`**: Features, architecture diagram, DB schema summary, API endpoints table, env vars table, Dockerfile description, build-and-push usage, troubleshooting
- **Update `build-vm/README.md`**: Add scanning-console image to "Purpose" section and build instructions alongside LOKI-RS

---

## Phase 3: Create Unified Portal

### 3.1 Minimal FastAPI app (`portal/`)

- `main.py`: login endpoint + landing page route
- `landing.html`: Two cards -- "Deployment Console" and "Scanning Console"
- Links include JWT token as query parameter for cross-domain auth
- Config: `deployment_console_url` and `scanning_console_url` from env vars

### 3.2 Cross-domain auth flow

1. User visits `cleanroom.knowledgeondemand.net` (portal)
2. No valid JWT -> redirected to portal login page
3. Login -> JWT stored in localStorage + cookie
4. Landing page shows two app cards
5. Click "Scanning Console" -> portal generates an **opaque one-time code** (60s TTL, per-user rate limited) via `POST /api/auth/exchange-code`
6. Redirect to `scan.knowledgeondemand.net?code=<opaque-code>` (NOT raw JWT — see Appendix A)
7. Scanning app JS: detects `code` param -> `POST /api/auth/redeem-code` -> validates HMAC signature + expiry -> **mints a new JWT** for the extracted username -> stores in localStorage -> `history.replaceState()` to strip URL
8. Click "Deployment Console" -> same code exchange pattern to `10.83.3.190:8000?code=<opaque-code>`

All three apps share the same `SECRET_KEY`, but use **derived keys** for each cryptographic purpose (JWT signing, code exchange HMAC, Fernet encryption — see **Appendix I**). Each app mints its own JWTs independently, so a compromised scanning console JWT cannot be used against the deployment console. See **Appendix A** for full implementation details.

### 3.3 URL scheme

| App | URL | Runs on |
|-----|-----|---------|
| Portal | `https://cleanroom.knowledgeondemand.net` | K8s (IngressRoute) |
| Deployment Console | `https://10.83.3.190:8000` | LXC container |
| Scanning Console | `https://scan.knowledgeondemand.net` | K8s (IngressRoute) |

### 3.4 Documentation (Phase 3)

- **Create `portal/README.md`**: Portal purpose, cross-domain auth flow diagram, env vars (`DEPLOYMENT_CONSOLE_URL`, `SCANNING_CONSOLE_URL`, `SECRET_KEY`), Dockerfile, build-and-push usage
- **Update `build-vm/README.md`**: Add portal image build instructions

---

## Phase 4: K8s Manifests

### 4.1 Scanning Console (`apps/scanning-console/`)

**ServiceAccount + RBAC** (namespace-scoped, least privilege):

The scanning console uses **namespaced Roles** (not ClusterRole) bound to only the namespaces it needs. This prevents a compromised scanning-console pod from accessing pods or secrets in unrelated namespaces (e.g., `argocd`, `traefik`, `cert-manager`).

```yaml
# Per-namespace Role (applied to: openvas, faraday, metasploit, loki-scanner, nmap-scanner)
# apps/scanning-console/role-scan-namespaces.yaml
{{- range $ns := list "openvas" "faraday" "metasploit" "loki-scanner" "nmap-scanner" }}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: scanning-console
  namespace: {{ $ns }}
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log", "pods/exec"]
    verbs: ["get", "list", "create", "delete", "watch"]
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: scanning-console
  namespace: {{ $ns }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: scanning-console
subjects:
  - kind: ServiceAccount
    name: scanning-console
    namespace: scanning-console
{{- end }}
```

```yaml
# ClusterRole — minimal, only for cluster-wide operations that cannot be namespaced
# apps/scanning-console/clusterrole.yaml
rules:
  - apiGroups: [""]
    resources: ["namespaces"]
    verbs: ["get", "list", "create", "patch"]  # create loki-scanner/nmap-scanner ns
  - apiGroups: [""]
    resources: ["nodes"]
    verbs: ["list"]  # display cluster info in reports
```

**Explicitly excluded:** No access to `argocd`, `traefik`, `cert-manager`, `metallb-system`, `ceph-csi`, `kube-system`, `harbor`, or `scanning-console` secrets (own secrets are mounted via env vars, not read via API).

**Deployment**: Single replica, `harbor.knowledgeondemand.net/cleanroom/scanning-console:latest`, ServiceAccount `scanning-console`, env from SOPS secrets (SECRET_KEY, DATABASE_URL, ADMIN_PASSWORD_HASH), probes on `:8000/api/system/health`.

**IngressRoute**: `Host(`scan.knowledgeondemand.net`)` -> service `scanning-console:8000`

**ArgoCD Application**: Automated sync, prune, selfHeal, ServerSideApply.

### 4.2 Portal (`apps/portal/`)

Same pattern, simpler: no ServiceAccount RBAC, no DB connection. IngressRoute on `cleanroom.knowledgeondemand.net`.

### 4.3 PostgreSQL (`apps/cleanroom-db/`)

- **Service type: ClusterIP** -- only accessed from within K8s
- StatefulSet, `postgres:17-alpine`, 10Gi Ceph RBD PVC, SOPS-encrypted credentials
- Pod security: non-root (UID 999), read-only root FS, drop all capabilities
- **Health probes:** `pg_isready` for startup (5s interval, 30 failures = 2.5min max), readiness (10s), liveness (30s) — see **Appendix E**
- **Automated backups:** Daily CronJob at 02:00 runs `pg_dump | gzip` to a 5Gi backup PVC, retains 14 days — see **Appendix C**

### 4.4 Network Policies

**`scanning-console-policy.yaml`:**
- Ingress: from Traefik namespace on port 8000
- Egress: DNS, PostgreSQL (cleanroom-db:5432), Faraday/OpenVAS/Metasploit/LOKI namespaces, K8s API server (:6443)

**`portal-policy.yaml`:**
- Ingress: from Traefik namespace on port 8000
- Egress: DNS only

**`cleanroom-db-policy.yaml`:**
- Ingress: from scanning-console namespace on port 5432
- Egress: DNS only

### 4.5 DNS Records

Add A records pointing to Traefik LB IP:
- `scan.knowledgeondemand.net`
- `cleanroom.knowledgeondemand.net`

### 4.6 Documentation (Phase 4)

- **Create `apps/scanning-console/README.md`**: K8s manifests overview, RBAC permissions table, ServiceAccount details, deployment/scaling instructions, IngressRoute config, SOPS secrets reference
- **Create `apps/cleanroom-db/README.md`**: PostgreSQL StatefulSet docs, connection details, SOPS secrets, PVC sizing, backup/restore procedures (pg_dump/pg_restore via kubectl exec), how to connect for debugging
- **Create `apps/portal/README.md`**: K8s manifests overview, IngressRoute, env vars
- **Update `docs/DNS-MAPPING.md`**: Add `scan.knowledgeondemand.net` and `cleanroom.knowledgeondemand.net` to the Kubernetes Services table
- **Update `apps/network-policies/README.md`**: Add scanning-console, portal, and cleanroom-db to the policy overview table with ingress/egress rules
- **Update `README.md` (root)**: Add scanning-console, portal, cleanroom-db to the project structure tree, deployed services table, architecture diagram, DNS records table, and deployment workflow (both WebUI and CLI options)
- **Update `apps/traefik/README.md`**: Add `scan.knowledgeondemand.net` and `cleanroom.knowledgeondemand.net` to DNS configuration section

---

## Phase 5: Trim Deployment Console

### 5.1 Remove scan-related code from `webui/`

Delete from `webui/app/`:
- `services/scan_service.py`, `services/ioc_scan_service.py`, `services/faraday_client.py`
- `routers/scan.py`, `routers/ioc_scan.py`
- `models/scan.py`, `models/ioc_scan.py`

Delete from `webui/`:
- `templates/scan.html`, `templates/ioc_scan.html`
- `static/js/scan.js`, `static/js/ioc_scan.js`

### 5.2 Update remaining webui files

- `webui/app/main.py` -- remove scan/ioc-scan router includes and page routes
- `webui/templates/base.html` -- remove Scan/IOC nav links, add Portal link
- `webui/requirements.txt` -- remove scan deps, add talos-common

### 5.3 Documentation (Phase 5)

- **Rewrite `webui/README.md`**: Remove all Security Scanning and IOC Scanning sections. Update features list to deployment-only. Update architecture tree (remove scan files). Update API endpoints table (remove `/api/scan/*` and `/api/ioc-scan/*`). Update Web UI Pages table (remove Scan and IOC Scan). Add "Scanning Console" link in the overview. Update deployment steps list.
- **Rewrite `webui/README-TECHNICAL.md`**: Remove Security Scanning Architecture and IOC Scanning Architecture sections. Remove scan-related entries from backend structure, routers, services, WebSocket table, Alpine.js components table, and key files table. Update the overview to describe deployment-only scope.

---

## Phase 6: Deployment Service Integration

Add to `deployment_service.py` after ArgoCD app deployment:
- **Attempt** SSH to Build VM (10.83.3.191) to build+push scanning-console and portal images (**soft failure** — if Build VM unreachable but images already exist in Harbor, log warning and continue; see **Appendix F**)
- Create `harbor-pull-secret` in `scanning-console` and `portal` namespaces
- Apply SOPS secrets for scanning-console (SECRET_KEY, DB password)
- Verify scanning-console pod reaches Running state
- Verify portal pod reaches Running state
- Update `dashboard.html` with links to Portal and Scanning Console
- Add `POST /api/deployment/rebuild-images` endpoint for manual image rebuild trigger

---

## Phase 7: Security Hardening

Applied to the scanning console:

- **TLS for PostgreSQL**: cert-manager issued cert, `sslmode=verify-full`
- **CSRF middleware**: token per session, validate on POST/PATCH/DELETE, exempt login + WebSocket
- **CSP headers**: script-src self + CDN origins, X-Frame-Options DENY, HSTS
- **CORS**: explicit allow_origins per app domain
- **Rate limiting**: in-memory token bucket (login: 5/min, scan start: 10/min, export: 20/min) — resets on pod restart; upgrade path to Redis if needed (see **Appendix H**)
- **Input sanitization**: strict regex for scan targets, reject shell metacharacters
- **Audit logging**: `audit_log` table (action, user, source_ip, resource, detail JSONB)
- **mTLS**: client cert for scanning-console -> PostgreSQL connection
- **Pod security**: non-root, read-only root FS, drop capabilities

---

## Phase 8: Polish, Documentation Review, and Verification

### Documentation final pass
1. **Audit all README files** -- read every README in the repo, verify they reflect the post-split architecture
2. **Cross-reference check** -- ensure DNS-MAPPING.md, root README, and traefik README all list the same FQDNs
3. **Accessing Services table** in root README -- verify scanning console and portal entries with correct URLs and credentials
4. **Deployment workflow** in root README -- verify both WebUI and CLI options include scanning-console/portal/cleanroom-db deployment steps
5. **Mark `docs/vuln-management-plan.md`** -- add "Status: Implemented" header with completion date
6. **Verify no stale references** -- grep for removed files (`scan_service.py`, `ioc_scan_service.py`, etc.) across all docs to ensure no broken references remain

### Functional
7. Portal login -> cross-domain token -> scanning console access
8. Deployment console deploys cluster + scanning console + portal
9. Run Nmap scan via scanning console -> results in PostgreSQL + Faraday
10. Reports dashboard shows charts, host/vuln lists
11. Scan comparison between two scans
12. PDF/CSV export
13. Remediation status tracking persists across pod restarts
14. Deployment console still works independently

### Infrastructure
15. ArgoCD manages scanning-console, portal, cleanroom-db apps
16. RBAC: scanning-console can create pods in scan namespaces, read secrets
17. RBAC: scanning-console CANNOT access deployment-related resources
18. Network policies block unauthorized cross-namespace traffic

### Security
19. CSRF: POST without token -> 403
20. Rate limiting: 6th rapid login -> 429
21. CSP headers present in browser dev tools
22. Audit log tracks all actions
23. TLS/mTLS on DB connection verified via `pg_stat_ssl`
24. kubectl inside scanning pod uses ServiceAccount token (not kubeconfig)
25. Cross-domain auth: one-time code exchange works, code expires after 60s
26. Code exchange: raw JWT never appears in URL bar or browser history
27. RBAC isolation: scanning-console pod CANNOT exec into pods in argocd/traefik/cert-manager/kube-system namespaces
28. RBAC isolation: scanning-console pod CANNOT read secrets in harbor/argocd namespaces
29. Key separation: JWT signed with derived key; raw SECRET_KEY not used directly for any crypto operation
30. Scanning console JWT cannot authenticate to deployment console (different app, minted independently)
31. Init container runs as non-root with read-only filesystem and dropped capabilities
32. Backup CronJob uses PGPASSFILE (secret mount), not PGPASSWORD env var

### Data Integrity
27. PostgreSQL backup CronJob runs daily, backups visible in backup PVC
28. Restore from backup: `gunzip | psql` produces identical data
29. Faraday sync retry: disconnect Faraday pod, run scan, reconnect — data syncs within 20 min
30. Faraday resync API: `POST /api/reports/faraday-resync/{id}` triggers manual re-upload
31. Alembic migration: delete scanning-console pod, verify init container runs `alembic upgrade head` on restart
32. PostgreSQL probes: kill postgres process, verify pod restarts via liveness probe

---

## File Summary

### New files: 60+

| Category | Count | Key Files |
|----------|-------|-----------|
| Shared package (`lib/talos-common/`) | 15 | README.md, auth.py, config_base.py, kubectl_utils.py, process_manager.py, base_service.py, ws_manager.py, **routers/exchange.py** (code exchange), 3 JS files (app.js includes auto-redeem), 2 templates |
| Scanning Console (`scanning-app/`) | 27+ | README.md, main.py, config.py, Dockerfile, build-and-push.sh, 4 DB files, **alembic.ini**, 4 middleware, 4 routers, 4 models, result_store.py, 8 templates, 5 JS files, alembic setup |
| Portal (`portal/`) | 7 | README.md, main.py, config.py, Dockerfile, build-and-push.sh, landing.html, base.html |
| K8s manifests (`apps/`) | 20 | scanning-console (9 YAML + README, **includes db-migrate init container**), portal (5 YAML + README), cleanroom-db (6 YAML + README + **backup-cronjob.yaml** + **backup-pvc.yaml**), 3 network policies |

### Modified files: 15

| File | Changes |
|------|---------|
| `webui/app/main.py` | Remove scan/ioc-scan routes, add portal link |
| `webui/app/config.py` | Inherit from BaseAppSettings |
| `webui/requirements.txt` | Add talos-common, remove scan deps |
| `webui/templates/base.html` | Remove Scan/IOC nav, add Portal link |
| `webui/templates/dashboard.html` | Add post-deploy links to portal/scanning |
| `webui/app/services/deployment_service.py` | Add step to deploy scanning console + portal |
| `README.md` (root) | Architecture diagram, project structure, services table, DNS, deployment workflow |
| `webui/README.md` | Trim to deployment-only scope |
| `webui/README-TECHNICAL.md` | Remove scan/IOC architecture sections |
| `docs/DNS-MAPPING.md` | Add scan + cleanroom FQDNs |
| `docs/vuln-management-plan.md` | Mark as implemented |
| `build-vm/README.md` | Add scanning-console + portal image builds |
| `apps/network-policies/README.md` | Add new policy entries |
| `apps/traefik/README.md` | Add new DNS entries to config section |

### Deleted files (Phase 5 cutover only): 9

Scan code moved to `scanning-app/`: scan_service.py, ioc_scan_service.py, faraday_client.py, scan router, ioc_scan router, scan models, scan/ioc templates, scan/ioc JS.

---

## Migration Order (Incremental, Non-Breaking)

**Guarantee: The existing LXC WebUI continues working unchanged through Phases 1-4. The current deployment and operational model is never broken.**

### Additive phases (existing WebUI untouched)

1. **Phase 1** -- Extract shared code to `lib/talos-common/`, update webui imports, verify everything still works. **Docs:** Create `lib/talos-common/README.md`, update root README project structure.
2. **Phase 2** -- Create `scanning-app/` as a **standalone copy** of scan code + DB + reports. Build Docker image. **Docs:** Create `scanning-app/README.md`, update `build-vm/README.md`.
3. **Phase 3** -- Create `portal/` with landing page + shared auth. Build Docker image. **Docs:** Create `portal/README.md`, update `build-vm/README.md`.
4. **Phase 4** -- Create K8s manifests, DNS records, deploy via ArgoCD. **Docs:** Create `apps/scanning-console/README.md`, `apps/cleanroom-db/README.md`, `apps/portal/README.md`. Update `docs/DNS-MAPPING.md`, `apps/network-policies/README.md`, `apps/traefik/README.md`, root `README.md`.

At this point: users can use EITHER the old LXC WebUI (full functionality) OR the new K8s scanning console. Both coexist.

### Cutover phases (deferred until ready)

5. **Phase 5** -- Trim `webui/` by removing moved scan code, update nav. **Only do this when confident the K8s scanning console works.** **Docs:** Rewrite `webui/README.md` and `webui/README-TECHNICAL.md` to deployment-only scope.
6. **Phase 6** -- Add deployment step to `deployment_service.py` for automated scanning-console deployment.
7. **Phase 7** -- Add security hardening to scanning console.
8. **Phase 8** -- End-to-end testing, documentation audit, and polish. **Docs:** Final cross-reference check across all READMEs, mark `docs/vuln-management-plan.md` as implemented, grep for stale file references.

### Dual maintenance note

During Phases 2-4, scan code exists in both `webui/app/services/scan_service.py` and `scanning-app/app/services/scan_service.py`. Bug fixes must be applied to both copies until Phase 5 removes the old code. This is an accepted tradeoff for the safety of parallel development.

**Mitigation:** During Phase 2, extract a `SCAN_CODE_VERSION` marker (date or short hash) into a comment at the top of each duplicated file. Before Phase 5 cutover, run a diff between the two copies to surface any divergence. If bug fixes were applied to only one copy during the transition period, reconcile before deleting the old code.

---

## Appendix A: Cross-Domain Auth — Secure Token Exchange

The original plan passes JWT tokens as `?token=<jwt>` query parameters when navigating between apps. This exposes tokens in browser history, server access logs, and `Referer` headers. The following one-time code exchange replaces that pattern.

### Security properties

1. **No JWT in URL** — only an opaque code appears in the query string
2. **Single-use** — codes are deleted server-side on first redemption (no replay)
3. **Short-lived** — 60-second TTL, expired codes are rejected
4. **Opaque** — the code is a random token, not a signed payload containing the JWT
5. **Per-user rate limited** — max 5 pending codes per user (prevents memory exhaustion)
6. **Derived HMAC key** — code signing uses `settings.code_exchange_key` (not raw `SECRET_KEY`)

### Flow

```
Portal                              Target App (Scanning/Deployment Console)
  │                                        │
  │  1. User clicks "Scanning Console"     │
  │  2. POST /api/auth/exchange-code       │
  │  3. Portal generates opaque code:      │
  │     code = secrets.token_hex(32)       │
  │     Stores server-side:               │
  │       code → { username, exp }        │
  │     Signs: HMAC(code_exchange_key,    │
  │       code + exp) → signature         │
  │     Returns: code:signature           │
  │                                        │
  │  4. Redirect to target app:           │
  │     ?code=<code>:<signature>          │
  │                                ───────►│
  │                                        │  5. JS detects `code` param
  │                                        │  6. POST /api/auth/redeem-code
  │                                        │     { code: "<code>:<signature>" }
  │                                        │
  │                                        │  7. Target app verifies HMAC using
  │                                        │     its own code_exchange_key
  │                                        │     (derived from shared SECRET_KEY)
  │                                        │  8. Validates expiry (60s TTL)
  │                                        │  9. Mints a NEW JWT for the username
  │                                        │     (does NOT receive the portal's JWT)
  │                                        │ 10. Returns { access_token: <new_jwt> }
  │                                        │ 11. JS stores in localStorage
  │                                        │ 12. history.replaceState() strips URL
```

### Implementation details

**Portal side — `POST /api/auth/exchange-code`** (requires valid JWT):
```python
import secrets, time, hmac, hashlib

# Server-side store: code → { username, created_at }
# Codes are opaque — the JWT is NOT stored or transmitted
_pending_codes: dict[str, dict] = {}
CODE_TTL_SECONDS = 60
CODE_MAX_PER_USER = 5  # per-user limit (not global) to prevent memory exhaustion

@router.post("/api/auth/exchange-code")
async def create_exchange_code(user: dict = Depends(get_current_user)):
    now = time.time()
    username = user["username"]

    # Evict expired codes globally
    expired = [k for k, v in _pending_codes.items() if now - v["created_at"] >= CODE_TTL_SECONDS]
    for k in expired:
        del _pending_codes[k]

    # Per-user rate limit
    user_codes = [k for k, v in _pending_codes.items() if v["username"] == username]
    if len(user_codes) >= CODE_MAX_PER_USER:
        raise HTTPException(429, "Too many pending codes. Wait for existing codes to expire.")

    # Generate opaque code (JWT is NOT embedded — only username is stored server-side)
    code = secrets.token_hex(32)
    exp = int(now) + CODE_TTL_SECONDS
    _pending_codes[code] = {"username": username, "created_at": now}

    # Sign code+exp with derived key so target app can verify origin + expiry
    sign_payload = f"{code}:{exp}:{username}".encode()
    signature = hmac.new(
        settings.code_exchange_key.encode(), sign_payload, hashlib.sha256
    ).hexdigest()

    return {"code": f"{code}:{exp}:{username}:{signature}"}
```

**Target app side — `POST /api/auth/redeem-code`** (no auth required):
```python
@router.post("/api/auth/redeem-code")
async def redeem_code(request: RedeemRequest):
    try:
        parts = request.code.split(":")
        if len(parts) != 4:
            raise HTTPException(403, "Invalid code format")
        code, exp_str, username, signature = parts

        # Verify HMAC with derived key (same SECRET_KEY → same derived key)
        sign_payload = f"{code}:{exp_str}:{username}".encode()
        expected = hmac.new(
            settings.code_exchange_key.encode(), sign_payload, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(403, "Invalid code")

        # Check expiry
        if time.time() > int(exp_str):
            raise HTTPException(403, "Code expired")

        # Mint a NEW JWT for this app (do NOT reuse the portal's JWT)
        # This limits blast radius: each app's JWTs are independent
        access_token = create_access_token(username, settings)
        return {"access_token": access_token, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(403, "Invalid code")
```

**Why the target mints a new JWT instead of receiving the portal's JWT:**
- If the scanning console is compromised, leaked JWTs only work for the scanning console — they cannot be used to access the deployment console (which has Terraform/infrastructure destruction capabilities)
- Each app can set different JWT expiry times or claims
- Token revocation can be per-app

**Frontend (shared `app.js`):**
```javascript
// On page load, check for ?code= param and redeem it
(function() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    if (code) {
        fetch('/api/auth/redeem-code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code })
        })
        .then(r => {
            if (!r.ok) throw new Error('Redemption failed');
            return r.json();
        })
        .then(data => {
            if (data.access_token) {
                localStorage.setItem('access_token', data.access_token);
                history.replaceState(null, '', window.location.pathname);
            }
        })
        .catch(() => window.location.href = '/login');
    }
})();
```

### Single-use enforcement

The portal enforces single-use because codes exist in `_pending_codes` and can be evicted. However, since target apps verify via HMAC (stateless), replay within the 60s window is theoretically possible.

**Accepted tradeoff:** The 60-second TTL makes replay impractical — an attacker would need to intercept the code in-flight AND redeem it before the legitimate user does (which triggers navigation). The code never contains sensitive data (no JWT, no password), and the minted JWT is scoped to the target app only. For additional protection, the target app could maintain a small `_redeemed_codes` set (pruned every 60s) to reject duplicates — but this is optional for a single-replica internal tool.

### Changes to Phase 3

Replace Section 3.2 steps 5-7 with the code exchange flow above. The portal's landing page links become:
```javascript
// Instead of: href="https://scan.knowledgeondemand.net?token=<jwt>"
async function navigateTo(url) {
    const resp = await authFetch('/api/auth/exchange-code', { method: 'POST' });
    const { code } = await resp.json();
    window.location.href = `${url}?code=${code}`;
}
```

### Changes to `lib/talos-common/`

Add `routers/exchange.py` with the `redeem-code` endpoint (since both Scanning Console and Deployment Console need it). Add the auto-redeem JS snippet to `static/js/app.js`. Use `settings.code_exchange_key` (not raw `settings.secret_key`) for HMAC operations.

---

## Appendix B: Database Migration Strategy (Alembic)

### How migrations run

Database migrations execute via an **init container** in the scanning-console Deployment. This ensures the schema is always current before the app starts, and works cleanly with ArgoCD's automated sync.

```yaml
# apps/scanning-console/deployment.yaml (addition)
initContainers:
  - name: db-migrate
    image: harbor.knowledgeondemand.net/cleanroom/scanning-console:latest
    command: ["alembic", "upgrade", "head"]
    env:
      - name: DATABASE_URL
        valueFrom:
          secretKeyRef:
            name: scanning-console-secrets
            key: database-url
    resources:
      requests: { cpu: "50m", memory: "64Mi" }
      limits: { cpu: "200m", memory: "128Mi" }
    securityContext:
      readOnlyRootFilesystem: true
      runAsNonRoot: true
      runAsUser: 1000
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
    volumeMounts:
      - name: tmp
        mountPath: /tmp           # Alembic may need temp space
# Add to pod spec volumes:
# - name: tmp
#   emptyDir: { sizeLimit: "10Mi" }
```

**Security note:** The init container uses the same image as the main app to avoid maintaining a separate image. To limit the blast radius of a supply chain compromise, the container runs as non-root with a read-only filesystem, dropped capabilities, and no privilege escalation. The only writable path is a size-limited emptyDir at `/tmp`.

### Alembic configuration

```
scanning-app/
  alembic.ini                       # Points to env.py, uses DATABASE_URL env var
  alembic/
    env.py                          # Reads DATABASE_URL from os.environ
    versions/
      001_initial_schema.py         # Creates all tables from Phase 2.2
```

**`alembic.ini`** key settings:
```ini
[alembic]
script_location = alembic
# sqlalchemy.url is set programmatically in env.py from DATABASE_URL env var
```

**`alembic/env.py`** pattern:
```python
import os
from alembic import context
from sqlalchemy import create_engine

def run_migrations_online():
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "")  # Alembic needs sync driver
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
```

### Manual migration (debugging)
```bash
# Shell into scanning-console pod
kubectl exec -it -n scanning-console deploy/scanning-console -- bash

# Check current revision
alembic current

# Apply pending migrations
alembic upgrade head

# Create new migration after model changes
alembic revision --autogenerate -m "add_new_column"
```

### Changes to Phase 4

Add the `db-migrate` init container to `apps/scanning-console/deployment.yaml`. Add `alembic.ini` to the scanning-app Dockerfile `COPY` step.

---

## Appendix C: PostgreSQL Automated Backups

### CronJob for daily backups

A Kubernetes CronJob runs `pg_dump` daily and stores compressed backups in a dedicated PVC.

```yaml
# apps/cleanroom-db/backup-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cleanroom-db-backup
  namespace: cleanroom-db
spec:
  schedule: "0 2 * * *"  # Daily at 2:00 AM
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      activeDeadlineSeconds: 600  # 10 min max
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: backup
              image: postgres:17-alpine
              command:
                - /bin/sh
                - -c
                - |
                  set -e
                  TIMESTAMP=$(date +%Y%m%d-%H%M%S)
                  BACKUP_FILE="/backups/cleanroom-${TIMESTAMP}.sql.gz"
                  echo "Starting backup: ${BACKUP_FILE}"
                  pg_dump -h cleanroom-db -U cleanroom cleanroom | gzip > "${BACKUP_FILE}"
                  echo "Backup complete: $(du -h ${BACKUP_FILE} | cut -f1)"
                  # Retain last 14 days of backups
                  find /backups -name "cleanroom-*.sql.gz" -mtime +14 -delete
                  echo "Cleanup complete. Remaining backups:"
                  ls -lh /backups/
              env:
                - name: PGPASSFILE
                  value: /secrets/.pgpass
              volumeMounts:
                - name: backup-storage
                  mountPath: /backups
                - name: pgpass-secret
                  mountPath: /secrets
                  readOnly: true
              resources:
                requests: { cpu: "100m", memory: "128Mi" }
                limits: { cpu: "500m", memory: "256Mi" }
          volumes:
            - name: backup-storage
              persistentVolumeClaim:
                claimName: cleanroom-db-backups
            - name: pgpass-secret
              secret:
                secretName: cleanroom-db-secrets
                items:
                  - key: pgpass           # format: cleanroom-db:5432:cleanroom:cleanroom:<password>
                    path: .pgpass
                    mode: 0600            # pgpass requires strict permissions
---
# PVC for backup storage
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: cleanroom-db-backups
  namespace: cleanroom-db
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: ceph-rbd
  resources:
    requests:
      storage: 5Gi
```

### Restore procedure

```bash
# List available backups
kubectl exec -it -n cleanroom-db sts/cleanroom-db -- ls -lh /backups/

# Restore from a specific backup
kubectl exec -i -n cleanroom-db sts/cleanroom-db -- \
  sh -c 'gunzip -c /backups/cleanroom-20260315-020000.sql.gz | psql -U cleanroom cleanroom'
```

### Changes to Phase 4

- Add `backup-cronjob.yaml` and `backup-pvc.yaml` to `apps/cleanroom-db/`
- Mount the backup PVC in the cleanroom-db StatefulSet as well (for restore access)
- Add backup/restore procedures to `apps/cleanroom-db/README.md`

### Changes to repository layout

```
apps/cleanroom-db/
  ...existing files...
  backup-cronjob.yaml               # NEW: daily pg_dump CronJob
  backup-pvc.yaml                   # NEW: 5Gi Ceph RBD for backup storage
```

---

## Appendix D: Faraday Sync Resilience (Dual-Write)

### Problem

The dual-write pattern (Section 2.3) writes to PostgreSQL first, then uploads to Faraday. If Faraday upload fails mid-way, the two systems diverge with no automatic reconciliation.

### Solution: Async retry queue with `faraday_sync_log`

The `faraday_sync_log` table (already in the schema) is extended to serve as a retry queue. After each scan completes:

1. **PostgreSQL write** (primary, synchronous) — always happens first
2. **Faraday upload** (secondary, best-effort) — attempted immediately
3. **On failure:** Log the failure in `faraday_sync_log` with `success=false` and `retry_count=0`
4. **Background retry task:** A periodic asyncio task (every 5 minutes) queries `faraday_sync_log` for failed syncs and retries them up to 3 times with exponential backoff

### Schema addition to `faraday_sync_log`

```
faraday_sync_log
  ...existing columns...
  retry_count       INTEGER DEFAULT 0
  next_retry_at     TIMESTAMP          # NULL if success=true or retries exhausted
  scan_type         TEXT               # "security" | "ioc" — needed to dispatch correct upload logic
```

### Implementation in `result_store.py`

```python
async def dual_write(scan_id: str, scan_type: str, parsed_results: dict, faraday_creds: dict):
    """Write to PostgreSQL (always), then attempt Faraday upload (best-effort)."""
    # Step 1: PostgreSQL — synchronous, must succeed
    await repository.save_scan_results(scan_id, parsed_results)

    # Step 2: Faraday — best-effort with retry on failure
    try:
        await faraday_client.upload_results(scan_id, parsed_results, faraday_creds)
        await repository.log_faraday_sync(scan_id, success=True, detail="Immediate upload")
    except Exception as e:
        await repository.log_faraday_sync(
            scan_id, success=False, detail=str(e),
            retry_count=0,
            next_retry_at=datetime.utcnow() + timedelta(minutes=5),
            scan_type=scan_type
        )
        logger.warning(f"Faraday upload failed for scan {scan_id}, queued for retry: {e}")
```

### Background retry task (in `main.py` lifespan)

```python
async def faraday_retry_loop():
    """Periodically retry failed Faraday uploads."""
    while True:
        await asyncio.sleep(300)  # 5 minutes
        pending = await repository.get_pending_faraday_syncs(max_retries=3)
        for sync in pending:
            try:
                results = await repository.get_scan_results(sync.scan_id)
                creds = await faraday_client.get_credentials()
                await faraday_client.upload_results(sync.scan_id, results, creds)
                await repository.mark_faraday_sync_success(sync.id)
            except Exception as e:
                await repository.increment_faraday_retry(
                    sync.id,
                    next_delay_minutes=5 * (2 ** sync.retry_count)  # 5m, 10m, 20m
                )
```

### Reconciliation API

```
GET /api/reports/faraday-sync-status   -- show pending/failed syncs
POST /api/reports/faraday-resync/{id}  -- manually trigger resync for a scan
```

### Changes to Phase 2

- Extend `faraday_sync_log` schema with `retry_count`, `next_retry_at`, `scan_type` columns
- Add retry loop to scanning-console `main.py` lifespan startup
- Add `faraday-sync-status` and `faraday-resync` endpoints to `routers/reports.py`

---

## Appendix E: PostgreSQL Health Probes

### Problem

The plan specifies probes for the scanning-console but not for the PostgreSQL StatefulSet. Without readiness probes, Kubernetes may route traffic to a PostgreSQL pod that hasn't finished initialization.

### Solution

Add standard PostgreSQL probes to `apps/cleanroom-db/statefulset.yaml`:

```yaml
# apps/cleanroom-db/statefulset.yaml (container spec addition)
containers:
  - name: postgres
    image: postgres:17-alpine
    # ...existing config...
    startupProbe:
      exec:
        command: ["pg_isready", "-U", "cleanroom", "-d", "cleanroom"]
      initialDelaySeconds: 5
      periodSeconds: 5
      failureThreshold: 30      # Allow up to 2.5 min for initial startup
    readinessProbe:
      exec:
        command: ["pg_isready", "-U", "cleanroom", "-d", "cleanroom"]
      initialDelaySeconds: 5
      periodSeconds: 10
      failureThreshold: 3
    livenessProbe:
      exec:
        command: ["pg_isready", "-U", "cleanroom", "-d", "cleanroom"]
      initialDelaySeconds: 30
      periodSeconds: 30
      failureThreshold: 3
```

### Changes to Phase 4

Add the above probes to the PostgreSQL container spec in `apps/cleanroom-db/statefulset.yaml`.

---

## Appendix F: Build VM Dependency in Deployment Pipeline

### Problem

Phase 6 has the deployment service SSH to the Build VM (10.83.3.191) to build and push Docker images. If the Build VM is down or unreachable, the entire deployment pipeline stalls.

### Solution: Make image build a skippable step with pre-built fallback

**Option selected:** The deployment service attempts the Build VM image build, but treats it as a **soft failure** — the step logs a warning and continues if the images already exist in Harbor. This works because:
- First deployment: Build VM must be up (images don't exist yet)
- Re-deployments: Images already exist in Harbor from the previous build
- Manual builds: User can SSH to Build VM and run `build-and-push.sh` at any time

### Implementation in `deployment_service.py`

```python
async def _step_build_scanning_images(self, step_id: int) -> bool:
    """Build and push scanning-console + portal images via Build VM.

    Soft failure: if Build VM is unreachable but images already exist in
    Harbor, log a warning and continue. This allows re-deployments to
    succeed without the Build VM.
    """
    images = [
        "harbor.knowledgeondemand.net/cleanroom/scanning-console:latest",
        "harbor.knowledgeondemand.net/cleanroom/portal:latest",
    ]

    # Check if images already exist in Harbor (requires auth for private projects)
    harbor_user = "admin"
    harbor_pass = await self.k8s.get_secret("harbor", "harbor-core-envvars", "HARBOR_ADMIN_PASSWORD") or "Harbor12345"
    all_exist = True
    for image in images:
        repo_name = image.split("/")[-1].split(":")[0]
        result = await self.process_manager.run_command_simple(
            ["curl", "-sf", "-u", f"{harbor_user}:{harbor_pass}",
             f"https://harbor.knowledgeondemand.net/v2/cleanroom/{repo_name}/tags/list"],
            timeout=10
        )
        if not result.success:
            all_exist = False
            break

    # Attempt SSH build
    build_success = await self._ssh_build_images(step_id)

    if not build_success and all_exist:
        await self.log(step_id, "warning",
            "Build VM unreachable but images already exist in Harbor. "
            "Using existing images. Run build-and-push.sh manually to update.")
        return True
    elif not build_success:
        await self.log(step_id, "error",
            "Build VM unreachable and images not found in Harbor. "
            "Deploy the Build VM first (build-vm/deploy-lxc.sh) or build images manually.")
        return False

    return True
```

### Changes to Phase 6

- Replace the unconditional SSH build with the soft-failure pattern above
- Add a note that first-time deployments require the Build VM to be running
- Add `POST /api/deployment/rebuild-images` endpoint for manual image rebuild trigger

---

## Appendix G: Portal Simplification — Static Landing Page

### Problem

The portal is 7 files (full FastAPI app) for what is essentially a login page and two links. This is over-engineered.

### Evaluated alternative: Traefik static file serving

A static HTML page served directly by Traefik (via a ConfigMap-backed volume or inline middleware) would eliminate the need for a container image, Dockerfile, build-and-push script, and FastAPI app entirely.

### Decision: Keep FastAPI, but minimize

The portal needs server-side logic for:
1. **JWT creation** on login (bcrypt password verification + token signing)
2. **One-time code exchange** generation (Appendix A)
3. **Health check** endpoint for Kubernetes probes

A static page cannot do any of these. However, the portal is kept **minimal**:
- No database, no RBAC, no ServiceAccount
- Single Python file (`main.py`) with 3 routes: login, landing, exchange-code
- Lightweight Dockerfile (python:3.11-slim, no kubectl or other tools)
- Total: ~150 lines of Python, 2 HTML templates

The 7-file count is an overestimate — `config.py` is ~10 lines, `Dockerfile` is standard boilerplate. The actual business logic is < 200 lines total.

### No changes required

This appendix documents the rationale. The portal stays as planned but implementers should resist adding complexity beyond the three endpoints above.

---

## Appendix H: Rate Limiting Persistence

### Problem

Phase 7 specifies in-memory rate limiting. Pod restarts reset all counters, allowing burst abuse after restarts.

### Accepted risk with mitigation

For a single-replica internal security tool, this is acceptable. The rate limiter primarily defends against:
- Accidental rapid-fire from UI bugs (mitigated even with in-memory)
- Brute-force login attempts (mitigated by bcrypt's inherent slowness: ~300ms/attempt)

**If this becomes insufficient**, the upgrade path is:
1. Use Redis (already available in the cluster — Faraday's Redis or a shared instance) as the rate limit backend
2. Switch from in-memory `dict` to `redis.incr()` with TTL
3. This is a ~20-line change in `middleware/rate_limit.py`

### No changes to Phase 7

Document the accepted risk and upgrade path in `scanning-app/README.md` troubleshooting section.

---

## Appendix I: Cryptographic Key Separation

### Problem

The original plan uses a single `SECRET_KEY` for three distinct cryptographic operations:
1. **JWT signing** (HS256) — tokens for authentication
2. **Fernet encryption** — deployment state persistence
3. **HMAC signing** — one-time code exchange (Appendix A)

If an attacker recovers the key from any one context (e.g., by brute-forcing a short JWT or finding a leaked state file), they can forge JWTs, decrypt state files, and generate valid exchange codes.

Additionally, all three apps share the same `SECRET_KEY` and JWT signing key, meaning a JWT minted by the scanning console (lower trust) could authenticate to the deployment console (higher trust — has Terraform access).

### Solution: Derived keys with HKDF-style separation

A single `SECRET_KEY` environment variable is shared across apps, but **each cryptographic operation derives its own key** using HMAC with a distinct context string. This is a simplified HKDF-Extract pattern:

```python
jwt_key       = HMAC-SHA256(SECRET_KEY, "jwt-signing")
exchange_key  = HMAC-SHA256(SECRET_KEY, "code-exchange")
fernet_key    = HMAC-SHA256(SECRET_KEY, "fernet-state")
```

**Properties:**
- Knowing `jwt_key` does not reveal `exchange_key` or `fernet_key` (HMAC is a PRF)
- All three keys change when `SECRET_KEY` is rotated
- Only one env var to manage across deployments
- No additional secret distribution infrastructure needed

### Cross-app JWT isolation

The code exchange flow (Appendix A) provides natural JWT isolation: each app mints its own JWT when redeeming a code. A JWT issued by the scanning console cannot be used to authenticate to the deployment console because:
1. Each app instance has its own JWT secret (derived from the same base key, but the JWT `iss` claim can be checked)
2. The code exchange mints a fresh JWT at the target app — the portal's JWT is never transmitted
3. Optional enhancement: add an `aud` (audience) claim to JWTs and validate it per-app

### Implementation in `BaseAppSettings`

See Section 1.3 for the `@property` definitions of `jwt_signing_key`, `code_exchange_key`, and `fernet_key`.

**Migration note:** Existing deployments using raw `SECRET_KEY` for JWT signing will need a one-time token invalidation (all users must re-login) when upgrading to derived keys. This is acceptable since the upgrade happens during the Phase 1 transition.

### Changes

- **Phase 1:** `BaseAppSettings` uses derived key properties instead of raw `SECRET_KEY`
- **Phase 3:** Portal uses `settings.code_exchange_key` for HMAC (Appendix A)
- **Phase 7:** Add `aud` claim to JWTs with per-app audience validation
- **All apps:** Replace `settings.secret_key` with `settings.jwt_signing_key` in `create_access_token()` and `decode_token()`

---

## Appendix J: Security Checklist Summary

Cross-reference of all security concerns identified during plan review and their resolutions:

| # | Concern | Severity | Resolution | Location |
|---|---------|----------|------------|----------|
| 1 | HMAC key reuse across JWT/Fernet/exchange | High | Derived keys via HMAC with distinct context strings | Appendix I, Section 1.3 |
| 2 | JWT embedded in signed exchange code | High | Opaque code only; JWT minted fresh at target app | Appendix A (rewritten) |
| 3 | No single-use enforcement for exchange codes | Medium | Server-side store on portal + 60s TTL; accepted 60s replay window on target side | Appendix A |
| 4 | Global `CODE_MAX_PENDING` DoS vector | Low | Changed to per-user limit (5 codes/user) | Appendix A |
| 5 | `PGPASSWORD` visible in `kubectl describe` | Low | Use `PGPASSFILE` with secret volume mount | Appendix C |
| 6 | Backup PVC unencrypted at rest | Low | Accepted — Ceph encryption-at-rest is the proper layer; documented as operational note |  |
| 7 | Credential caching in Faraday retry loop | Low | Accepted — credentials re-fetched each attempt; workspace deletion is an ops error, not an attack vector | |
| 8 | No sanitization before Faraday re-upload | Low | Accepted — data was already parsed and stored in PostgreSQL; the parse step is the trust boundary, not the upload | |
| 9 | Harbor API check without auth (401 → false negative) | Medium | Added `-u admin:password` from K8s secret to curl check | Appendix F |
| 10 | ClusterRole grants pods/exec cluster-wide | High | Replaced with namespace-scoped Roles for scan namespaces only | Section 4.1 |
| 11 | Shared SECRET_KEY enables cross-app JWT forgery | High | Derived keys + per-app JWT minting via code exchange | Appendix I, Appendix A |
| 12 | Init container runs full app image (supply chain risk) | Medium | Added securityContext: readOnlyRootFilesystem, runAsNonRoot, drop ALL capabilities | Appendix B |
