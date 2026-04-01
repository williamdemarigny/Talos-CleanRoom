# Vulhub Integration Plan — K8s-Based Vulnerable Targets

> **Status:** Proposed (2026-04-01)
> **Branch:** `refactor/restructure`
> **Goal:** Add Vulhub Docker-based vulnerable environments as K8s-deployable targets alongside existing Proxmox VM targets (Metasploitable3).

---

## 1. Architecture Overview

The current Target Lab deploys Metasploitable3 VMs on Proxmox (clone template, configure cloud-init IP, start, wait for QEMU guest agent, destroy). Vulhub targets are fundamentally different: sets of 1-3 Docker containers defined by `docker-compose.yml` files, translated to K8s Deployments + Services in isolated namespaces.

A new `VulhubTargetService` sits alongside the existing `TargetLabService`, both accessible through the existing router. The router delegates to the right backend based on target type. A new DB model `VulhubTarget` tracks K8s-deployed environments separately from `TargetVM`.

**Key difference from Proxmox VMs:**
- No Proxmox API, no cloud-init, no QEMU guest agent
- Scanner tools reach targets via K8s Service DNS (`svc.namespace.svc.cluster.local`)
- Namespace-per-environment isolation (delete namespace = full cleanup)
- Lighter weight: shorter TTL (2h default), higher concurrency (8 max)

---

## 2. Vulhub Environment Catalog

Curated static catalog shipped as a Python module. Each entry references pre-built K8s manifests stored in the repo.

### Recommended Initial Set (20 environments)

| Category | Vulhub Environment | CVE | Description |
|----------|-------------------|-----|-------------|
| **RCE** | `log4j/CVE-2021-44228` | CVE-2021-44228 | Log4Shell — Apache Log4j2 JNDI RCE |
| **RCE** | `spring/CVE-2022-22965` | CVE-2022-22965 | Spring4Shell — Spring Framework RCE |
| **TLS** | `openssl/CVE-2014-0160` | CVE-2014-0160 | Heartbleed — TLS information leak |
| **Web** | `apache/struts2/s2-045` | CVE-2017-5638 | Struts2 RCE (Equifax breach vector) |
| **Web** | `drupal/CVE-2018-7600` | CVE-2018-7600 | Drupalgeddon 2 |
| **Web** | `wordpress/pwnscriptum` | CVE-2016-10033 | WordPress PHPMailer RCE |
| **Web** | `tomcat/CVE-2017-12615` | CVE-2017-12615 | Tomcat PUT method RCE |
| **Auth** | `shiro/CVE-2016-4437` | CVE-2016-4437 | Apache Shiro deserialization |
| **Auth** | `libssh/CVE-2018-10933` | CVE-2018-10933 | libssh auth bypass |
| **SSRF** | `weblogic/CVE-2014-4210` | CVE-2014-4210 | Oracle WebLogic SSRF |
| **XXE** | `weblogic/CVE-2017-10271` | CVE-2017-10271 | WebLogic XMLDecoder RCE |
| **SQLi** | `mysql/CVE-2012-2122` | CVE-2012-2122 | MySQL auth bypass |
| **NoSQL** | `mongo-express/CVE-2019-10758` | CVE-2019-10758 | mongo-express RCE |
| **Network** | `samba/CVE-2017-7494` | CVE-2017-7494 | SambaCry RCE |
| **Network** | `redis/4-unacc` | N/A | Unauthorized Redis access |
| **Network** | `elasticsearch/CVE-2015-1427` | CVE-2015-1427 | Elasticsearch Groovy RCE |
| **DNS** | `bind9/CVE-2017-3143` | CVE-2017-3143 | BIND TSIG bypass |
| **PHP** | `php/CVE-2019-11043` | CVE-2019-11043 | PHP-FPM RCE |
| **Misc** | `nginx/insecure-configuration` | N/A | Nginx misconfiguration examples |
| **Container** | `docker/CVE-2019-5736` | CVE-2019-5736 | runc container escape (demo only) |

### Catalog Data Structure

New file: `scanning-app/app/services/vulhub_catalog.py`

```python
VULHUB_CATALOG = {
    "log4shell": {
        "name": "Log4Shell (CVE-2021-44228)",
        "cve": "CVE-2021-44228",
        "category": "rce",
        "description": "Apache Log4j2 JNDI RCE — the most impactful CVE of 2021",
        "services": ["Java App (8983)"],
        "ports": [8983],
        "images": ["vulhub/solr:8.11.0"],
        "manifest": "vulhub-manifests/log4shell.yaml",
        "difficulty": "easy",
    },
    # ... 19 more entries
}
```

---

## 3. Deployment Mechanism

**Decision: Hand-crafted K8s YAML manifests per environment (not Kompose or Helm).**

Rationale:
- Vulhub docker-compose files are simple (1-3 containers). Kompose output is messy.
- Helm is overkill for environments this simple.
- Hand-crafted manifests allow precise resource limits, security contexts, and labels.

### Manifest Structure

New directory: `apps/vulhub-targets/manifests/`

Each manifest is a single YAML containing: Deployment(s), Service(s). The service creates these dynamically on deploy:
- Namespace (named `vulhub-{env_id}-{uuid[:6]}`)
- NetworkPolicy
- ResourceQuota

### Why ClusterIP (Not NodePort)

Scanner tools (Nmap, OpenVAS, Metasploit) run as pods inside the cluster. They reach ClusterIP services natively via DNS. NodePort would unnecessarily expose vulnerable services to the host network.

Target address for scanners: `svc-name.vulhub-log4shell-a1b2c3.svc.cluster.local:8983`

---

## 4. Service Layer

### New Service: `scanning-app/app/services/vulhub_target_service.py`

```python
class VulhubTargetService:
    def get_catalog(self, category=None) -> list[dict]
    async def deploy_target(self, env_id: str, username: str) -> dict
    async def destroy_target(self, target_id: int, username: str) -> dict
    async def extend_ttl(self, target_id: int, hours: int) -> dict
    async def list_targets(self) -> list[dict]
    async def get_target(self, target_id: int) -> dict
    async def get_capacity(self) -> dict
    async def cleanup_expired(self)
    async def reconcile_orphaned(self)
```

### Deploy Flow

1. Look up `env_id` in `VULHUB_CATALOG`
2. Check capacity (max 8 concurrent Vulhub targets)
3. Generate namespace: `vulhub-{env_id}-{uuid[:6]}`
4. Create namespace with label `app.kubernetes.io/part-of: vulhub-targets`
5. Apply manifest YAML via `kubectl apply -f -`
6. Apply NetworkPolicy + ResourceQuota
7. Wait for Deployment(s) ready (`kubectl rollout status`)
8. Record in DB with status, namespace, service DNS, TTL
9. Return target info

### Destroy Flow

1. Look up target in DB
2. Delete namespace: `kubectl delete namespace {ns}` (cascading cleanup)
3. Update DB status to "destroyed"

---

## 5. Database Changes

### New Model: `VulhubTarget`

New file: `scanning-app/alembic/versions/005_add_vulhub_targets.py`

```python
class VulhubTarget(Base):
    __tablename__ = "vulhub_targets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    env_id = Column(String, nullable=False)          # catalog key, e.g. "log4shell"
    name = Column(String, nullable=False)             # display name
    namespace = Column(String, unique=True, nullable=False)
    service_endpoint = Column(String, nullable=False) # DNS:port for scanning
    cve_id = Column(String, nullable=True)
    category = Column(String, nullable=True)
    status = Column(String, nullable=False, default="deploying")
    created_at = Column(DateTime, default=func.now())
    ttl_expires_at = Column(DateTime, nullable=False)
    created_by = Column(String, nullable=True)
    destroyed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    ports_json = Column(JSONB, nullable=True)
```

**Why separate table?** Proxmox VMs need `vmid`, `proxmox_node`, `ip_address`; Vulhub targets need `namespace`, `service_endpoint`, `env_id`, `cve_id`. A shared table would be full of nullable columns.

---

## 6. API Endpoints

New endpoints in `scanning-app/app/routers/target_lab.py`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/target-lab/vulhub/catalog` | Catalog with optional `?category=` filter |
| GET | `/api/target-lab/vulhub/catalog/{env_id}` | Single environment detail |
| POST | `/api/target-lab/vulhub/deploy` | Deploy environment `{"env_id": "log4shell"}` |
| POST | `/api/target-lab/vulhub/destroy/{target_id}` | Destroy target |
| POST | `/api/target-lab/vulhub/extend/{target_id}` | Extend TTL |
| GET | `/api/target-lab/vulhub/targets` | List active targets |
| GET | `/api/target-lab/vulhub/status/{target_id}` | Target status |

Existing Proxmox VM endpoints remain unchanged.

---

## 7. UI Changes

Restructure `scanning-app/templates/target_lab.html` into three sections:

1. **Proxmox VM Templates** (existing, unchanged)
2. **Vulhub Environments** (new):
   - Category filter tabs: All / RCE / Web / Network / Database / Misc
   - Cards with: name, CVE (linked to NVD), description, difficulty badge, ports, Deploy button
   - Search by CVE ID or name
3. **Active Targets** (unified table):
   - Both Proxmox VMs and Vulhub targets in one table
   - "Type" column: "Proxmox VM" or "Vulhub K8s"
   - "Address" column: IP for VMs, service DNS for Vulhub
   - "Scan This Target" button navigates to `/scan?target={endpoint}`

---

## 8. Network Policies

### Per-Vulhub Namespace (applied during deploy)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: vulhub-target-isolation
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: nmap-scanner
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: openvas
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: metasploit
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: scanning-console
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - protocol: UDP
          port: 53
    - to:
        - podSelector: {}  # intra-namespace (multi-container envs)
```

### Scanning Console Egress Update

Add to `apps/network-policies/scanning-console-policy.yaml`:

```yaml
- to:
    - namespaceSelector:
        matchLabels:
          app.kubernetes.io/part-of: vulhub-targets
```

---

## 9. Config Settings

Add to `scanning-app/app/config.py`:

```python
vulhub_targets_enabled: bool = True
vulhub_target_ttl_hours: int = 2
vulhub_target_max_concurrent: int = 8
vulhub_image_registry: str = ""           # Empty = Docker Hub; set to Harbor mirror
vulhub_target_cpu_limit: str = "500m"
vulhub_target_memory_limit: str = "512Mi"
```

---

## 10. Image Management

**Harbor mirror (recommended for production):**
1. Create Harbor project `vulhub` at `harbor.knowledgeondemand.net/vulhub/`
2. Script `scripts/mirror-vulhub-images.sh` pulls curated images → pushes to Harbor
3. `vulhub_image_registry` config rewrites image refs in manifests
4. Run mirror script manually or on schedule when adding new environments

**Fallback:** If registry is empty, pull from Docker Hub directly.

---

## 11. RBAC Changes

Update `apps/scanning-console/rbac.yaml` — the scanning-console ClusterRole needs permissions to manage resources in dynamically-created namespaces:

```yaml
- apiGroups: ["", "apps", "networking.k8s.io"]
  resources: ["deployments", "services", "pods", "networkpolicies", "resourcequotas"]
  verbs: ["get", "list", "create", "delete", "patch"]
```

---

## 12. Implementation Sequence

### Phase 1 — Foundation
1. `scanning-app/app/services/vulhub_catalog.py` — Static catalog
2. `scanning-app/alembic/versions/005_add_vulhub_targets.py` — Migration
3. `scanning-app/app/db/models.py` — Add `VulhubTarget` model
4. `scanning-app/app/config.py` — Add Vulhub config settings

### Phase 2 — K8s Manifests
5. `apps/vulhub-targets/manifests/` — Start with 5: log4shell, spring4shell, heartbleed, struts2-s2045, drupalgeddon2
6. Base NetworkPolicy and ResourceQuota templates

### Phase 3 — Service Layer
7. `scanning-app/app/services/vulhub_target_service.py` — Core service
8. `scanning-app/app/routers/target_lab.py` — Add Vulhub endpoints
9. `scanning-app/app/main.py` — Register cleanup loop

### Phase 4 — UI
10. `scanning-app/templates/target_lab.html` — Vulhub catalog section
11. `scanning-app/static/js/target_lab.js` — Alpine.js handlers

### Phase 5 — Infrastructure
12. `apps/scanning-console/rbac.yaml` — Expand RBAC
13. `apps/network-policies/scanning-console-policy.yaml` — Vulhub egress
14. `scripts/mirror-vulhub-images.sh` — Harbor mirroring

---

## 13. What to Keep

| Item | Reason |
|------|--------|
| Metasploitable3 Proxmox VM targets | Full OS scanning (not just web services) |
| `target_lab_service.py` | Proxmox VM lifecycle unchanged |
| `proxmox_client.py` | Still needed for VM targets |
| `prepare-metasploitable3-templates.sh` | Still needed if user wants VM targets |

---

## 14. Potential Challenges

1. **Multi-container startup ordering** — Some Vulhub envs have dependencies (web app + database). Translate `depends_on` to readiness probes / init containers.
2. **Volume initialization** — Some envs use named volumes for init scripts. Translate to ConfigMaps.
3. **Image pull latency** — First deploy without cached images may take 30-60s. Harbor pre-pull mitigates this.
4. **DNS resolution in scanner pods** — Verify Nmap/OpenVAS/Metasploit images resolve `.svc.cluster.local` names.
5. **RBAC scope** — Dynamic namespace creation requires broad ClusterRole. Mitigate with label selectors and service-layer validation.
