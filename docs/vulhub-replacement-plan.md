# Plan: Replace Metasploitable3 VM Targets with Vulhub K8s Targets

> **Status:** Proposed (2026-04-01)
> **Branch:** `refactor/restructure`
> **Prerequisite:** Read `docs/vulhub-integration-plan.md` for catalog details, manifest strategy, and network policy templates.

---

## Summary

Remove the entire Proxmox-based Metasploitable3 Target Lab (VM cloning, cloud-init, guest agent, template preparation) and replace it with Vulhub Docker-based vulnerable environments deployed as K8s workloads. This eliminates all Proxmox API dependencies from the Scanning Console.

---

## Phase 1: Files to DELETE

| File | Reason |
|------|--------|
| `scanning-app/app/services/target_lab_service.py` | Proxmox VM lifecycle — replaced by `vulhub_target_service.py` |
| `scanning-app/app/services/proxmox_client.py` | Proxmox API client — only imported by `target_lab_service.py` |
| `scripts/prepare-metasploitable3-templates.sh` | Metasploitable3 template builder — no longer needed |

---

## Phase 2: Database Migration

**New file:** `scanning-app/alembic/versions/005_replace_target_vms_with_vulhub.py`

- **DROP** `target_vms` table (ephemeral data, no historical value)
- **CREATE** `vulhub_targets` table:

```python
class VulhubTarget(Base):
    __tablename__ = "vulhub_targets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    env_id = Column(String, nullable=False)           # catalog key, e.g. "log4shell"
    name = Column(String, nullable=False)              # display name
    namespace = Column(String, unique=True, nullable=False)  # k8s namespace
    service_endpoint = Column(String, nullable=False)  # DNS:port for scanning
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

**Indexes:** `ix_vulhub_targets_status`, `ix_vulhub_targets_ttl`

**downgrade():** Recreate `target_vms` from 004 schema for rollback safety.

---

## Phase 3: Files to CREATE

### 3a. Catalog — `scanning-app/app/services/vulhub_catalog.py`

Static Python dict of 20 curated environments. See `docs/vulhub-integration-plan.md` Section 2 for the full list. Each entry:

```python
"log4shell": {
    "name": "Log4Shell (CVE-2021-44228)",
    "cve": "CVE-2021-44228",
    "category": "rce",
    "description": "Apache Log4j2 JNDI RCE",
    "services": ["Solr (8983)"],
    "ports": [8983],
    "images": ["vulhub/solr:8.11.0"],
    "manifest": "log4shell.yaml",
    "difficulty": "easy",
},
```

### 3b. Service — `scanning-app/app/services/vulhub_target_service.py`

Follow the same patterns as `target_lab_service.py` (singleton, advisory lock, DB session management). Methods:

| Method | Description |
|--------|-------------|
| `get_catalog(category=None)` | Return filtered catalog entries |
| `deploy_target(env_id, username)` | Create namespace, apply manifest + NetworkPolicy + ResourceQuota, wait for rollout, record in DB |
| `destroy_target(target_id, username)` | Delete namespace (cascading), update DB |
| `extend_ttl(target_id, hours)` | Extend TTL (max 12h from creation) |
| `list_targets()` | Return all active (non-destroyed) targets |
| `cleanup_expired()` | Destroy targets past TTL |
| `reconcile_orphaned()` | Detect DB records whose namespace is gone, mark destroyed |
| `close()` | Cleanup on shutdown |

**Deploy flow:**
1. Look up `env_id` in `VULHUB_CATALOG` (404 if not found)
2. Check capacity (max `vulhub_target_max_concurrent` active targets)
3. Generate namespace: `vulhub-{env_id}-{uuid[:6]}`
4. `kubectl create namespace {ns}` with label `app.kubernetes.io/part-of: vulhub-targets`
5. Apply manifest YAML from baked-in file path (`/app/vulhub-manifests/{manifest}`)
6. Apply NetworkPolicy (scanner ingress only, DNS-only egress + intra-namespace)
7. Apply ResourceQuota (from config: CPU, memory, pod limits)
8. `kubectl rollout status deployment/{name} -n {ns} --timeout=120s`
9. Record in DB: env_id, name, namespace, service_endpoint, cve_id, category, status=running, TTL
10. Return target info dict

**Service endpoint format:** `{svc-name}.{namespace}.svc.cluster.local:{port}`

### 3c. K8s Manifests — `apps/vulhub-targets/manifests/`

Start with 5 environments. Each is a single YAML with Deployment(s) + Service(s). No Namespace/NetworkPolicy/ResourceQuota in the manifest — those are created dynamically by the service.

Initial set:
- `log4shell.yaml` — Solr 8.11.0 (port 8983)
- `spring4shell.yaml` — Spring app (port 8080)
- `heartbleed.yaml` — Nginx with vulnerable OpenSSL (port 443)
- `struts2-s2045.yaml` — Struts2 app (port 8080)
- `drupalgeddon2.yaml` — Drupal 7 + MySQL (ports 80, 3306)

### 3d. Image Mirror Script — `scripts/mirror-vulhub-images.sh` (optional, Phase 8)

Pulls curated Vulhub images from Docker Hub → pushes to Harbor at `harbor.knowledgeondemand.net/vulhub/`.

---

## Phase 4: Files to MODIFY

### 4a. `scanning-app/app/db/models.py`

- **Remove:** `TargetVM` class (lines 221-241)
- **Add:** `VulhubTarget` class (as defined above)

### 4b. `scanning-app/app/config.py`

**Remove** (lines 28-43):
```python
# Target Lab (Proxmox API for Metasploitable3 VMs)
proxmox_api_url: str = ""
proxmox_api_token: str = ""
target_lab_enabled: bool = True
target_vm_ttl_hours: int = 4
target_vm_max_concurrent: int = 4
target_vm_vmid_start: int = 5000
target_vm_ip_start: str = "10.83.3.160"
target_vm_ip_count: int = 10
target_vm_vlan_id: int = 3
target_vm_network_bridge: str = "vmbr0"
target_vm_proxmox_node: str = ""
target_vm_gateway: str = "10.83.3.1"
target_vm_netmask: str = "255.255.255.0"
metasploitable3_ubuntu_vmid: int = 4000
metasploitable3_windows_vmid: int = 4001
```

**Add:**
```python
# Target Lab (Vulhub K8s-based vulnerable environments)
target_lab_enabled: bool = True
vulhub_target_ttl_hours: int = 2
vulhub_target_max_concurrent: int = 8
vulhub_manifests_dir: str = "/app/vulhub-manifests"
vulhub_target_cpu_limit: str = "500m"
vulhub_target_memory_limit: str = "512Mi"
```

### 4c. `scanning-app/app/routers/target_lab.py`

**Complete rewrite.** Replace all Proxmox VM endpoints with Vulhub endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/catalog` | List catalog (optional `?category=` filter) |
| GET | `/catalog/{env_id}` | Single environment detail |
| GET | `/targets` | List active targets |
| GET | `/targets/{target_id}` | Single target status |
| POST | `/deploy` | Deploy `{"env_id": "log4shell"}` |
| POST | `/destroy/{target_id}` | Destroy target |
| POST | `/extend/{target_id}` | Extend TTL `{"hours": 2}` |
| GET | `/capacity` | Current/max capacity |

Remove all imports of `target_lab_service`, `proxmox_client`, `TargetVM`. Import `vulhub_target_service` instead.

### 4d. `scanning-app/app/main.py`

**Replace** all `target_lab_service` references with `vulhub_target_service`:
- Line 21: Import `target_lab` router — keep (same router module, just rewritten)
- Lines 36-55: `_target_lab_cleanup_loop()` — change to import/use `VulhubTargetService`
- Lines 58-59: Lifespan reconcile — change to `VulhubTargetService`
- Lines 73-74: Lifespan shutdown — change to `VulhubTargetService`

### 4e. `scanning-app/templates/target_lab.html`

**Complete rewrite.** Replace Proxmox VM template cards with:

1. **Vulhub Catalog** section:
   - Category filter tabs: All / RCE / Web / Network / Auth / Misc
   - Card grid with: name, CVE badge (linked to NVD), description, difficulty, ports, Deploy button
   - Search/filter by name or CVE

2. **Active Targets** table:
   - Columns: Name, CVE, Category, Endpoint, Status, TTL Remaining, Actions (Scan/Extend/Destroy)
   - "Scan This Target" → navigates to `/scan?target={service_endpoint}`

### 4f. `scanning-app/static/js/target_lab.js`

**Complete rewrite.** Replace Proxmox VM Alpine.js component with Vulhub version:
- `loadCatalog()` → `GET /api/target-lab/catalog`
- `loadTargets()` → `GET /api/target-lab/targets` (poll every 10s)
- `deploy(envId)` → `POST /api/target-lab/deploy`
- `destroy(targetId)` → `POST /api/target-lab/destroy/{id}`
- `extendTtl(targetId)` → `POST /api/target-lab/extend/{id}`
- Category filter, search filter logic
- TTL countdown display

### 4g. `scanning-app/Dockerfile`

**Add** after existing COPY lines:
```dockerfile
COPY apps/vulhub-targets/manifests/ ./vulhub-manifests/
```

This bakes the manifest YAMLs into the container image so `kubectl apply` can reference them.

### 4h. `apps/scanning-console/deployment.yaml`

**Remove** (lines 117-129):
```yaml
# Target Lab (Proxmox API for Metasploitable3 VMs)
- name: PROXMOX_API_URL
  valueFrom:
    secretKeyRef:
      name: scanning-console-credentials
      key: proxmox-api-url
      optional: true
- name: PROXMOX_API_TOKEN
  valueFrom:
    secretKeyRef:
      name: scanning-console-credentials
      key: proxmox-api-token
      optional: true
```

### 4i. `apps/scanning-console/rbac.yaml`

**Add** to ClusterRole rules (needed for dynamic namespace management):
```yaml
- apiGroups: [""]
  resources: ["namespaces", "resourcequotas"]
  verbs: ["get", "list", "create", "delete", "patch"]
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "create", "delete", "patch"]
- apiGroups: [""]
  resources: ["services"]
  verbs: ["get", "list", "create", "delete"]
- apiGroups: ["networking.k8s.io"]
  resources: ["networkpolicies"]
  verbs: ["get", "list", "create", "delete"]
```

### 4j. `apps/network-policies/scanning-console-policy.yaml`

**Remove** (line ~97 area):
```yaml
# Target VM subnet
- to:
    - ipBlock:
        cidr: 10.83.3.160/28
```

**Add:**
```yaml
# Vulhub target namespaces (K8s-based vulnerable environments)
- to:
    - namespaceSelector:
        matchLabels:
          app.kubernetes.io/part-of: vulhub-targets
```

### 4k. `webui/app/models/deployment.py`

**Change** step 20 (line 94):
```python
# Before:
DeploymentStep(id=20, name="prepare_target_templates", description="Prepare Target VM Templates"),
# After:
DeploymentStep(id=20, name="prepare_vulhub_targets", description="Prepare Vulhub Target Environments"),
```

### 4l. `webui/app/services/deployment_service.py`

**Step 20** (`_step_prepare_target_templates`, lines 2848-2924):
Replace entire method with `_step_prepare_vulhub_targets` that:
- Pre-pulls Vulhub images to worker nodes (optional, can just log a note)
- OR simply verifies the scanning-console has the manifests baked in and RBAC is sufficient
- This step becomes much simpler — no SSH, no Proxmox, no template building

**Secret generation** (lines 2330-2343):
Remove the Proxmox credential injection into scanning-console-credentials:
```python
# Remove these lines:
proxmox_creds = self._read_proxmox_credentials()
proxmox_api_url = proxmox_creds.get("proxmox_api_url", "")
proxmox_api_token = proxmox_creds.get("proxmox_api_token", "")
# ...
if proxmox_api_url:
    sc_secret_data["proxmox-api-url"] = proxmox_api_url
if proxmox_api_token:
    sc_secret_data["proxmox-api-token"] = proxmox_api_token
```

**SOPS template** (lines ~2407-2410):
Remove proxmox-api-url and proxmox-api-token from scanning-console SOPS content.

**Cleanup method** (lines 984-1002):
Remove the target lab VM/template destruction block:
```python
# Remove: "Step 5: Destroy target lab VMs and templates..."
# Remove: target_vmids = set(range(5000, 5100)) | {4000, 4001}
# Remove: all lab_vms destruction logic
```

Also update line 1027 — remove `| set(range(5000, 5100)) | {4000, 4001}` from `managed_vmids`.

**IMPORTANT — Keep:**
- `_read_proxmox_credentials()` — still used by cleanup (Terraform VMs, Build VM) and Build VM step
- All other Proxmox SSH code — used for Build VM provisioning, not target lab
- `proxmox_host` / `proxmox_ssh_user` settings — used by cleanup and Build VM

---

## Phase 5: Credential Vault Update

The deployment service generates a credentials vault YAML. Search for any "Target Lab", "Metasploitable", or "Proxmox" entries in the vault and remove them. The scanning-console credentials entry should no longer mention Proxmox API URL/token.

---

## Phase 6: Documentation Updates

### `CLAUDE.md`
- Remove references to Metasploitable3, VMIDs 4000/4001, target VM IP range 10.83.3.160-169
- Update Target Lab description to reference Vulhub K8s environments
- Update scanning-console config table

### `docs/vulhub-integration-plan.md`
- Update status from "Proposed" to "Implemented" and update Section 13 ("What to Keep") to reflect removal

### `DEPLOYMENT.md`
- Remove step about running `prepare-metasploitable3-templates.sh`
- Update Target Lab section to describe Vulhub environments

---

## Implementation Order

| Phase | Files | Type |
|-------|-------|------|
| 1 | `vulhub_catalog.py` | Create |
| 2 | `005_replace_target_vms_with_vulhub.py` | Create |
| 3 | `models.py` (remove TargetVM, add VulhubTarget) | Modify |
| 4 | `config.py` (remove Proxmox settings, add Vulhub) | Modify |
| 5 | `apps/vulhub-targets/manifests/*.yaml` (5 manifests) | Create |
| 6 | `vulhub_target_service.py` | Create |
| 7 | `target_lab.py` router (rewrite) | Modify |
| 8 | `main.py` (swap service references) | Modify |
| 9 | `target_lab.html` (rewrite UI) | Modify |
| 10 | `target_lab.js` (rewrite JS) | Modify |
| 11 | `Dockerfile` (add COPY manifests) | Modify |
| 12 | Delete `target_lab_service.py`, `proxmox_client.py`, `prepare-metasploitable3-templates.sh` | Delete |
| 13 | `deployment.yaml` (remove Proxmox env vars) | Modify |
| 14 | `rbac.yaml` (add namespace/deployment RBAC) | Modify |
| 15 | `scanning-console-policy.yaml` (swap target rules) | Modify |
| 16 | `deployment_service.py` (remove step 20 template prep, remove Proxmox secrets, remove cleanup block) | Modify |
| 17 | `deployment.py` models (rename step 20) | Modify |
| 18 | Documentation updates | Modify |

---

## Verification Checklist

**Database:**
- [ ] `alembic upgrade head` creates `vulhub_targets`, drops `target_vms`
- [ ] `alembic downgrade 004` rolls back cleanly

**API:**
- [ ] `GET /api/target-lab/catalog` returns 20 environments
- [ ] `GET /api/target-lab/catalog?category=rce` filters correctly
- [ ] `POST /api/target-lab/deploy {"env_id":"log4shell"}` creates namespace + deployment
- [ ] Namespace labeled `app.kubernetes.io/part-of: vulhub-targets`
- [ ] NetworkPolicy + ResourceQuota applied
- [ ] `GET /api/target-lab/targets` shows running target with service endpoint
- [ ] `POST /api/target-lab/destroy/{id}` deletes namespace
- [ ] TTL extension works, caps at 12h from creation
- [ ] Cleanup loop destroys expired targets

**Scanning:**
- [ ] Nmap can scan `svc.vulhub-*.svc.cluster.local` DNS target
- [ ] OpenVAS can create target with DNS name
- [ ] Metasploit modules can reach Vulhub services

**Network:**
- [ ] Scanner namespaces can reach vulhub target pods
- [ ] Vulhub pods cannot reach internet (DNS-only egress)
- [ ] Vulhub pods cannot reach non-scanner namespaces

**No Proxmox residue in scanning-app:**
- [ ] `grep -r "proxmox" scanning-app/` returns 0 results
- [ ] `grep -r "metasploitable" scanning-app/` returns 0 results
- [ ] `grep -r "4000\|4001\|5000" scanning-app/app/` returns 0 false positives
- [ ] No `PROXMOX_API_URL` or `PROXMOX_API_TOKEN` in deployment.yaml

**Proxmox code preserved where needed:**
- [ ] `_read_proxmox_credentials()` still works in deployment_service.py
- [ ] Cleanup still destroys Terraform VMs and Build VM
- [ ] Build VM provisioning (step 19) unaffected

**UI:**
- [ ] Target Lab page shows Vulhub catalog with category filters
- [ ] Deploy/Destroy/Extend buttons work
- [ ] "Scan This Target" navigates to scan page with DNS endpoint
- [ ] No references to Proxmox, VMID, Metasploitable3 in UI
