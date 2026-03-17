# Talos CleanRoom — End-to-End Deployment Guide

Complete deployment instructions for standing up the full Talos CleanRoom platform on a fresh Proxmox cluster.

> **Estimated time:** 2–3 hours (mostly waiting for pods, image builds, and feed syncs).

This guide is organized into two paths:
- **[Automated Deployment (WebUI)](#automated-deployment-webui)** — recommended, uses the Deployment Console to orchestrate K8s cluster creation
- **[Manual Deployment](#manual-deployment)** — step-by-step CLI commands for full control

Both paths share the same [Prerequisites](#1-prerequisites) and [Initial Setup](#initial-setup-both-paths) (steps 1–4).

---

## Prerequisites

### Proxmox Cluster

| Node | IP | Role |
|------|----|------|
| pve01 | 10.83.2.20 | Proxmox host + Ceph monitor |
| pve02 | 10.83.2.21 | Proxmox host + Ceph monitor |
| pve03 | 10.83.2.22 | Proxmox host + Ceph monitor |
| pve04 | 10.83.2.23 | Proxmox host + Ceph monitor |

Requirements:
- Proxmox VE 7.x or 8.x
- Ceph storage pool configured (used by Terraform for VM disks and by K8s for PVs)
- VLAN 3 configured on network bridge `vmbr0` (subnet `10.83.3.0/24`, gateway `10.83.3.1`)
- Talos ISO uploaded to Ceph shared storage: `cephfs:iso/metal-amd64.iso` (download from [factory.talos.dev](https://factory.talos.dev))
- Debian 12 LXC template available: `cephfs:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst`
- Proxmox API token created (e.g., `terraform@pve!provider=<secret>`)

### Workstation Tools

Install these on the machine where you run the deployment:

| Tool | Version | Purpose |
|------|---------|---------|
| terraform | ≥ 1.7 | VM and LXC provisioning |
| kubectl | ≥ 1.29 | Kubernetes management |
| talosctl | latest | Talos cluster management |
| talhelper | latest | Talos config generation |
| sops | ≥ 3.8 | Secret encryption/decryption |
| age | latest | Encryption key generation (used by SOPS) |
| helm | ≥ 3.x | Helm chart operations |
| jq | any | JSON processing |
| git | any | Repository access |
| htpasswd | any | Password hash generation (for Traefik) |

### Network

| Resource | IP / Range |
|----------|-----------|
| Control plane | 10.83.3.10 |
| Workers | 10.83.3.15–17 |
| MetalLB pool | 10.83.3.200–250 |
| Deployment Console (LXC) | 10.83.3.190 |
| Build VM (LXC) | 10.83.3.191 |
| Pod CIDR | 10.14.0.0/16 |
| Service CIDR | 10.15.0.0/16 |

### Access

- SSH key with access to the private GitHub repository
- SOPS Age key file at `~/.config/sops/age/keys.txt` (or generate in step 1)
- Cloudflare API token for DNS-01 TLS certificate challenges

---

# Initial Setup (Both Paths)

Steps 1–4 are required regardless of which deployment path you choose.

## 1. Workstation Setup

Clone the repository and check out the deployment branch:

```bash
git clone git@github.com:williamdemarigny/Talos-CleanRoom.git
cd Talos-CleanRoom
git checkout refactor/restructure
```

## 2. Generate Secrets

Generate SOPS-encrypted Kubernetes secrets for all applications:

```bash
# Generate Age key if you don't have one
age-keygen -o ~/.config/sops/age/keys.txt

# Generate all application secrets (passwords, hashes, etc.)
./scripts/generate-secrets.sh
```

This creates encrypted secret files for:
- **ArgoCD** — admin password (bcrypt hash)
- **Traefik** — dashboard basic auth credentials
- **OpenVAS** — admin + database passwords
- **Faraday** — admin + database passwords
- **Metasploit** — database + RPC passwords
- **CleanRoom DB** — PostgreSQL password
- **Scanning Console** — secret key, database URL, admin hash (shares SECRET_KEY with Portal for SSO)
- **Portal** — secret key, admin hash (reuses Scanning Console values for SSO)
- **Portal Credential Vault** — aggregated credentials for all services (displayed in Portal UI)
- **Threat Dragon** — encryption key, JWT signing + refresh keys

Use `--dry-run` to preview without writing files.

## 3. Commit and Push to Git

The SOPS-encrypted secrets must be in the git remote before ArgoCD can decrypt and apply them:

```bash
git add apps/*/secrets.sops.yaml apps/portal/credential-vault.sops.yaml apps/traefik/basic-auth-secret.sops.yaml apps/argocd/secrets.sops.yaml cluster/talsecret.sops.yaml
git commit -m "Generate secrets for fresh deployment"
git push
```

> **Important:** ArgoCD uses KSOPS to decrypt `.sops.yaml` files from the git repo. If secrets are not pushed, ArgoCD apps will fail with missing secret errors.

## 4. Choose Your Deployment Path

You now have two options:

| Path | Best for | What it automates |
|------|----------|-------------------|
| **[Automated (WebUI)](#automated-deployment-webui)** | Most users | K8s cluster creation, ArgoCD, infra stack, security tools |
| **[Manual](#manual-deployment)** | Debugging, customization | Nothing — you run every command |

---

# Automated Deployment (WebUI)

The WebUI (Deployment Console) runs in a Proxmox LXC container and orchestrates the entire K8s cluster deployment through a web interface. Follow these steps in order.

## A1. Deploy the Deployment Console

The Deployment Console has **no Kubernetes dependency** — it *creates* the K8s cluster.

```bash
cd webui
chmod +x deploy-lxc.sh
./deploy-lxc.sh
```

The script prompts for:
- Proxmox API token
- Proxmox SSH password
- LXC root password
- `deploy` user password
- GitHub SSH key path
- WebUI admin password (default: `admin`)

| Setting | Value |
|---------|-------|
| VMID | 200 |
| IP | 10.83.3.190 |
| Cores / RAM / Disk | 2 / 2 GB / 20 GB |
| Port | 8000 |
| Installed | Python 3.11, terraform, kubectl, helm, talosctl, talhelper, sops |

Verify it's running:

```bash
ssh deploy@10.83.3.190
sudo systemctl status deployment-webui
```

Access at `http://10.83.3.190:8000` (login: `admin` / `admin`).

## A2. Deploy the Kubernetes Cluster

Open `http://10.83.3.190:8000`, login, and click **Deploy**.

The WebUI runs a 17-step automated deployment:

| Steps | What |
|-------|------|
| 0–1 | Validate git repo + check dependencies |
| 2–3 | Terraform VMs on Proxmox + wait for boot |
| 4–5 | Generate + apply Talos machine configs |
| 6–7 | Verify cluster health + retrieve kubeconfig |
| 8 | Install ArgoCD |
| 9 | Infrastructure stack (MetalLB, cert-manager, Traefik, Ceph CSI) |
| 10 | ArgoCD self-management |
| 11–15 | Security tools (OpenVAS, Faraday, Metasploit, Threat Dragon, Harbor) |
| 16 | Configure integrations |

Wait for all 17 steps to complete. The K8s cluster is now running with ArgoCD, full infrastructure, and all security tools including Harbor.

## A3. Download Kubeconfig

The WebUI generated the kubeconfig during deployment and stored it on the WebUI LXC. Your local workstation needs a copy for all remaining steps.

1. In the WebUI at `http://10.83.3.190:8000`, go to the **Deployment** page
2. Click **Download Kubeconfig** to save `kubeconfig.yaml`
3. Move it into place:

```bash
mkdir -p ~/.kube
cp ~/Downloads/kubeconfig.yaml ~/.kube/config
```

> **Windows:** If your browser saves to a different location, adjust the `cp` path accordingly.

4. Verify you can reach the cluster:

```bash
kubectl get nodes
```

Expected: 1 control-plane + 3 worker nodes in `Ready` state.

> **Note:** All remaining steps (A4 onward) require `kubectl` access and should be run from your **local workstation** with the kubeconfig and the repo checked out.

## A4. Configure DNS

Create DNS A records pointing to the Traefik LoadBalancer IP:

```bash
kubectl get svc traefik -n traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
```

Required DNS records (typically 10.83.3.200):

| FQDN | Target |
|------|--------|
| `traefik.knowledgeondemand.net` | Traefik LB IP |
| `argocd.knowledgeondemand.net` | Traefik LB IP |
| `harbor.knowledgeondemand.net` | Traefik LB IP |
| `openvas.knowledgeondemand.net` | Traefik LB IP |
| `faraday.knowledgeondemand.net` | Traefik LB IP |
| `threatdragon.knowledgeondemand.net` | Traefik LB IP |
| `scan.knowledgeondemand.net` | Traefik LB IP |
| `cleanroom.knowledgeondemand.net` | Traefik LB IP |

If using Cloudflare, these can be a single wildcard record: `*.knowledgeondemand.net → 10.83.3.200`.

See [docs/DNS-MAPPING.md](docs/DNS-MAPPING.md) for the complete reference.

## A5. Apply Application Secrets

> **Run from:** Local workstation (repo checkout with kubeconfig from A3)

Decrypt and apply the SOPS-encrypted secrets to the K8s cluster:

```bash
./scripts/apply-secrets.sh
```

Or apply individually:

```bash
sops -d apps/openvas/secrets.sops.yaml       | kubectl apply -f -
sops -d apps/faraday/secrets.sops.yaml       | kubectl apply -f -
sops -d apps/metasploit/secrets.sops.yaml    | kubectl apply -f -
sops -d apps/traefik/basic-auth-secret.sops.yaml | kubectl apply -f -
sops -d apps/threat-dragon/secrets.sops.yaml | kubectl apply -f -
sops -d apps/scanning-console/secrets.sops.yaml | kubectl apply -f -
sops -d apps/portal/secrets.sops.yaml        | kubectl apply -f -
sops -d apps/portal/credential-vault.sops.yaml | kubectl apply -f -
sops -d apps/cleanroom-db/secrets.sops.yaml  | kubectl apply -f -
```

> **Important:** Secrets must exist before pods that reference them start. If a pod is in `CreateContainerConfigError`, apply its secret and it will auto-recover.

## A6. Deploy the Build VM

> **Run from:** Local workstation (repo checkout)

The Build VM is a Proxmox LXC container with Docker CE for building container images. It needs the K8s cluster running (for kubeconfig) and Harbor running (to push images).

```bash
cd build-vm
chmod +x deploy-lxc.sh
./deploy-lxc.sh
```

The script prompts for:
- Proxmox API token
- Proxmox SSH password
- LXC root password
- `deploy` user password (for SSH access)
- GitHub SSH key path (auto-detects common locations)
- Kubeconfig path (for creating Harbor pull secrets in K8s)

| Setting | Value |
|---------|-------|
| VMID | 201 |
| IP | 10.83.3.191 |
| Cores / RAM / Disk | 2 / 4 GB / 50 GB |
| Installed | Docker CE, kubectl, curl, jq, git |

Verify:

```bash
ssh deploy@10.83.3.191
docker info    # should show Docker engine running
```

If the kubeconfig wasn't copied during deployment, copy it now:

```bash
scp ~/.kube/config deploy@10.83.3.191:~/.kube/config
```

## A7. Build and Push Container Images

> **Run from:** Build VM (SSH to `deploy@10.83.3.191`)

SSH into the Build VM and build all three custom images:

```bash
ssh deploy@10.83.3.191
cd /opt/talos-cleanroom
git pull    # ensure latest code
```

### LOKI-RS IOC Scanner

```bash
cd apps/loki
chmod +x build-and-push.sh
./build-and-push.sh
```

This script:
1. Creates the `cleanroom` project in Harbor (idempotent)
2. Creates `harbor-pull-secret` in the `loki-scanner` namespace
3. Builds the LOKI-RS image (`ubuntu:24.04` base + FUSE + SSHFS + CIFS)
4. Pushes to `harbor.knowledgeondemand.net/cleanroom/loki-rs-scanner:v2.10.0`

### Scanning Console

Both Scanning Console and Portal require the **repo root** as the Docker build context (they depend on `lib/talos-common`):

```bash
cd /opt/talos-cleanroom
docker build -f scanning-app/Dockerfile -t harbor.knowledgeondemand.net/cleanroom/scanning-console:latest .
docker push harbor.knowledgeondemand.net/cleanroom/scanning-console:latest
```

### Portal

```bash
cd /opt/talos-cleanroom
docker build -f portal/Dockerfile -t harbor.knowledgeondemand.net/cleanroom/portal:latest .
docker push harbor.knowledgeondemand.net/cleanroom/portal:latest
```

### Verify images in Harbor

```bash
curl -sk https://harbor.knowledgeondemand.net/api/v2.0/projects/cleanroom/repositories | jq '.[].name'
```

Expected: `cleanroom/loki-rs-scanner`, `cleanroom/scanning-console`, `cleanroom/portal`.

### Create Harbor Pull Secrets

The `loki-scanner` namespace gets its pull secret from `build-and-push.sh`, but scanning-console and portal need theirs:

```bash
for ns in scanning-console portal; do
    kubectl create secret docker-registry harbor-pull-secret \
        --namespace="$ns" \
        --docker-server=harbor.knowledgeondemand.net \
        --docker-username=admin \
        --docker-password=Harbor12345 \
        2>/dev/null || echo "  harbor-pull-secret already exists in $ns"
done
```

## A8. Deploy CleanRoom Database

> **Run from:** Local workstation (requires kubectl)

PostgreSQL 17 backing the Scanning Console:

```bash
kubectl apply -f apps/cleanroom-db/application.yaml
```

Wait for ArgoCD to sync and create the resources, then verify:

```bash
# Wait for ArgoCD to sync (watch until SYNC=Synced, HEALTH=Healthy)
kubectl -n argocd get application cleanroom-db -w

# Verify StatefulSet is ready
kubectl -n cleanroom-db rollout status statefulset/cleanroom-db --timeout=300s

# Verify PostgreSQL is accepting connections
kubectl -n cleanroom-db exec statefulset/cleanroom-db -- pg_isready
```

## A9. Deploy Scanning Console

The Scanning Console provides vulnerability scanning (Nmap, OpenVAS, Metasploit, LOKI-RS IOC) with PostgreSQL persistence. The deployment includes an init container that runs Alembic database migrations before the app starts.

```bash
kubectl apply -f apps/scanning-console/application.yaml
```

Wait for ArgoCD to sync, then verify:

```bash
kubectl -n argocd get application scanning-console -w
kubectl -n scanning-console rollout status deployment/scanning-console --timeout=300s
```

Verify at `https://scan.knowledgeondemand.net`.

## A10. Deploy Unified Portal

The Portal is the landing page providing SSO across all three applications:

```bash
kubectl apply -f apps/portal/application.yaml
```

Wait for ArgoCD to sync, then verify:

```bash
kubectl -n argocd get application portal -w
kubectl -n portal rollout status deployment/portal --timeout=120s
```

Verify at `https://cleanroom.knowledgeondemand.net`.

## A11. Apply Network Policies

Apply zero-trust network policies (default-deny per namespace with explicit allow rules):

```bash
kubectl apply -f apps/network-policies/
```

This creates policies for: faraday, openvas, threat-dragon, metasploit, argocd, scanning-console, portal, cleanroom-db.

> **Tip:** Network policies are applied last so you can verify all services are working before locking down traffic. If a service stops working after applying policies, temporarily remove the policy for that namespace to confirm it's the cause: `kubectl delete networkpolicy -n <namespace> --all`

See [apps/network-policies/README.md](apps/network-policies/README.md) for the full policy matrix.

## A12. Post-Deployment Verification

### Service Access Points

| Service | URL | Default Credentials |
|---------|-----|-------------------|
| Deployment Console | `http://10.83.3.190:8000` | admin / admin |
| Portal | `https://cleanroom.knowledgeondemand.net` | admin / admin |
| Scanning Console | `https://scan.knowledgeondemand.net` | admin / admin |
| ArgoCD | `https://argocd.knowledgeondemand.net` | admin / (generated) |
| Harbor | `https://harbor.knowledgeondemand.net` | admin / Harbor12345 |
| OpenVAS | `https://openvas.knowledgeondemand.net` | admin / admin |
| Faraday | `https://faraday.knowledgeondemand.net` | admin / (k8s secret) |
| Threat Dragon | `https://threatdragon.knowledgeondemand.net` | — (no auth) |
| Traefik Dashboard | `https://traefik.knowledgeondemand.net` | admin / (generated) |

### Verification Checklist

```bash
# 1. All K8s nodes are Ready
kubectl get nodes

# 2. ArgoCD shows all apps synced
kubectl -n argocd get applications

# 3. All pods are running
kubectl get pods -A | grep -v Running | grep -v Completed

# 4. Traefik has external IP
kubectl get svc traefik -n traefik

# 5. Ceph storage is working
kubectl get pvc -A

# 6. Harbor has images
curl -sk https://harbor.knowledgeondemand.net/api/v2.0/projects/cleanroom/repositories | jq '.[].name'

# 7. CleanRoom DB is healthy
kubectl -n cleanroom-db exec statefulset/cleanroom-db -- pg_isready

# 8. Scanning Console is up
curl -sk https://scan.knowledgeondemand.net/api/system/health

# 9. Portal is up
curl -sk https://cleanroom.knowledgeondemand.net/api/system/health

# 10. Run a quick Nmap scan from the Scanning Console to validate end-to-end
```

### Test Cross-App SSO

1. Login to the Portal at `https://cleanroom.knowledgeondemand.net`
2. Click the Scanning Console link — should SSO without re-entering credentials
3. Click the Deployment Console link — should SSO to `http://10.83.3.190:8000`

## A13. Change Default Credentials

**Do this before any production use.**

| Service | How to Change |
|---------|--------------|
| **Deployment Console** | Edit `.env` on LXC, regenerate bcrypt hash, restart service |
| **Scanning Console** | Update `scanning-console-credentials` K8s secret, restart pod |
| **Portal** | Update `portal-credentials` K8s secret, restart pod |
| **ArgoCD** | `argocd account update-password` or update secret |
| **Harbor** | Change via Harbor web UI on first login |
| **OpenVAS** | Update `openvas-credentials` K8s secret, restart pod |
| **Faraday** | Update `faraday-credentials` K8s secret, restart pod |
| **Traefik** | Regenerate `basic-auth-secret` with `htpasswd` |

Generate a bcrypt hash for WebUI/Scanning Console/Portal:

```bash
python3 -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('your-new-password'))"
```

---

## Automated Deployment Summary

```
Local Workstation
    ├─ [1]  Clone repo
    ├─ [2]  generate-secrets.sh           → SOPS-encrypted secrets
    ├─ [3]  git commit + push             → Secrets available for ArgoCD
    │
Proxmox (run from local workstation)
    ├─ [A1] WebUI deploy-lxc.sh           → Deployment Console (10.83.3.190)
    │
WebUI (browser)
    ├─ [A2] WebUI "Deploy" button         → K8s cluster + ArgoCD + infra + security tools
    │       (automated, ~45 min)
    │
Local Workstation (run from repo checkout with kubeconfig)
    ├─ [A3] Retrieve kubeconfig           → Copy from WebUI LXC or download from WebUI
    ├─ [A4] DNS records                   → *.knowledgeondemand.net
    ├─ [A5] apply-secrets.sh              → App secrets into K8s
    ├─ [A6] Build VM deploy-lxc.sh        → Docker build env (10.83.3.191)
    │
Build VM (SSH to 10.83.3.191)
    ├─ [A7] Build + push images           → LOKI-RS, scanning-console, portal
    │
Local Workstation
    ├─ [A8]  CleanRoom DB                 → PostgreSQL 17
    ├─ [A9]  Scanning Console             → Scanning web app
    ├─ [A10] Portal                       → SSO landing page
    ├─ [A11] Network policies             → Zero-trust (applied last)
    └─ [A12] Verification                → End-to-end checks
```

---

# Manual Deployment

If you prefer full control or need to debug individual steps, follow this path instead of the automated one. Complete [Initial Setup](#initial-setup-both-paths) (steps 1–4) first.

You can also use `DeployCluster.sh` as a CLI alternative — see [CLI Script](#cli-script-deployclustersh) below.

## M1. Create Kubernetes VMs (Terraform)

```bash
cd terraform/cluster-create
```

Create `credentials.auto.tfvars` (this file is gitignored):

```hcl
proxmox_api_url      = "https://pve01.knowledgeondemand.net:8006"
proxmox_api_token    = "terraform@pve!provider=YOUR-TOKEN-SECRET"
proxmox_ssh_password = "YOUR-PROXMOX-ROOT-PASSWORD"
```

The VM specs are defined in `cluster.auto.tfvars`:

| Node | VMID | Role | Cores | RAM | Disk |
|------|------|------|-------|-----|------|
| talos-CleanRoom-master-01 | 2000 | Control plane | 4 | 24 GB | 30 GB |
| talos-CleanRoom-worker-01 | 3001 | Worker | 4 | 24 GB | 30 GB |
| talos-CleanRoom-worker-02 | 3002 | Worker | 4 | 24 GB | 30 GB |
| talos-CleanRoom-worker-03 | 3003 | Worker | 4 | 24 GB | 30 GB |

Edit `cluster.auto.tfvars` if you need different specs or MAC addresses.

```bash
terraform init
terraform plan    # review what will be created
terraform apply   # confirm with 'yes'
```

This creates 4 VMs on Proxmox booting from the Talos ISO. VMs will be in maintenance mode waiting for configuration.

## M2. Bootstrap Talos Kubernetes Cluster

```bash
cd ../../cluster

# Generate cluster secrets (first time only)
talhelper gensecret > talsecret.sops.yaml
sops -e -i talsecret.sops.yaml

# Generate machine configs from talconfig.yaml + talenv.yaml
talhelper genconfig --env-file talenv.yaml
```

This creates machine config files in `clusterconfig/` for each node.

### Apply Configs to VMs

```bash
./apply-configs.sh
```

The script:
1. Reads Proxmox credentials from `../terraform/cluster-create/credentials.auto.tfvars`
2. Discovers DHCP IPs assigned to each VM via the Proxmox guest agent API
3. Applies the correct Talos machine config to each node
4. Waits for Talos API readiness (port 50000)
5. Retries up to 5 times per node with diagnostics on failure

### Bootstrap the Cluster

```bash
# Bootstrap etcd on the control plane
talosctl bootstrap --nodes 10.83.3.10

# Wait for the cluster to come up (1-2 minutes)
talosctl health --nodes 10.83.3.10

# Get kubeconfig
talosctl kubeconfig --nodes 10.83.3.10 -f ~/.kube/config

# Verify all nodes are Ready
kubectl get nodes
```

Expected output: 1 control-plane + 3 worker nodes in `Ready` state.

## M3. Install ArgoCD

```bash
# Create namespace
kubectl create namespace argocd

# Apply ArgoCD Application (self-managed via Helm chart)
kubectl apply -f apps/argocd/application.yaml

# Wait for ArgoCD to be ready
kubectl -n argocd rollout status deployment/argocd-server --timeout=300s

# Get the initial admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
echo  # newline
```

ArgoCD is now running but not yet accessible via ingress — that comes after Traefik is deployed.

## M4. Deploy Infrastructure Stack

This deploys the core infrastructure in dependency order:

```bash
cd apps
chmod +x deploy-ingress-stack.sh
./deploy-ingress-stack.sh
```

The script runs 13 steps:
1. Check prerequisites (kubectl, ArgoCD running)
2. Pre-create namespaces (`metallb-system`, `cert-manager`, `traefik`, `ceph-csi`)
3. Deploy **Metrics Server** (sync-wave -2)
4. Deploy **MetalLB** (sync-wave -2) — L2 load balancer, IP pool 10.83.3.200–250
5. Deploy **cert-manager** (sync-wave -1) — TLS certificate management
6. Apply Cloudflare DNS-01 secret and ClusterIssuers
7. Deploy **Traefik** (sync-wave 0) — ingress controller, fixed LB IP 10.83.3.200
8. Deploy **Ceph CSI RBD** (sync-wave 0) — StorageClass `ceph-rbd`
9. Apply Traefik IngressRoutes (dashboard, ArgoCD)
10. Test Ceph CSI with a test PVC (up to 15 min on fresh clusters)

After completion, verify:

```bash
# Traefik has an external IP
kubectl get svc traefik -n traefik

# Ceph StorageClass exists
kubectl get storageclass ceph-rbd

# cert-manager is ready
kubectl get pods -n cert-manager
```

## M5. Configure DNS

Create DNS A records pointing to the Traefik LoadBalancer IP. Get the IP:

```bash
kubectl get svc traefik -n traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
```

Required DNS records (typically 10.83.3.200):

| FQDN | Target |
|------|--------|
| `traefik.knowledgeondemand.net` | Traefik LB IP |
| `argocd.knowledgeondemand.net` | Traefik LB IP |
| `harbor.knowledgeondemand.net` | Traefik LB IP |
| `openvas.knowledgeondemand.net` | Traefik LB IP |
| `faraday.knowledgeondemand.net` | Traefik LB IP |
| `threatdragon.knowledgeondemand.net` | Traefik LB IP |
| `scan.knowledgeondemand.net` | Traefik LB IP |
| `cleanroom.knowledgeondemand.net` | Traefik LB IP |

If using Cloudflare, these can be a single wildcard record: `*.knowledgeondemand.net → 10.83.3.200`.

See [docs/DNS-MAPPING.md](docs/DNS-MAPPING.md) for the complete reference.

## M6. Apply Application Secrets

Decrypt and apply the SOPS-encrypted secrets to the K8s cluster:

```bash
./scripts/apply-secrets.sh
```

Or apply individually:

```bash
sops -d apps/openvas/secrets.sops.yaml       | kubectl apply -f -
sops -d apps/faraday/secrets.sops.yaml       | kubectl apply -f -
sops -d apps/metasploit/secrets.sops.yaml    | kubectl apply -f -
sops -d apps/traefik/basic-auth-secret.sops.yaml | kubectl apply -f -
sops -d apps/threat-dragon/secrets.sops.yaml | kubectl apply -f -
sops -d apps/scanning-console/secrets.sops.yaml | kubectl apply -f -
sops -d apps/portal/secrets.sops.yaml        | kubectl apply -f -
sops -d apps/portal/credential-vault.sops.yaml | kubectl apply -f -
sops -d apps/cleanroom-db/secrets.sops.yaml  | kubectl apply -f -
```

Use `--dry-run` to preview: `./scripts/apply-secrets.sh --dry-run`
Use `--app <name>` to target one app: `./scripts/apply-secrets.sh --app metasploit`

> **Important:** Secrets must exist before pods that reference them start. If a pod is in `CreateContainerConfigError`, apply its secret and it will auto-recover.

## M7. Deploy Security Tools

Apply each ArgoCD Application. They auto-sync and self-heal.

```bash
# Harbor container registry (needed before image builds)
kubectl apply -f apps/harbor/application.yaml

# OpenVAS vulnerability scanner
kubectl apply -f apps/openvas/application.yaml

# Faraday vulnerability management
kubectl apply -f apps/faraday/application.yaml

# Metasploit penetration testing framework
kubectl apply -f apps/metasploit/application.yaml

# Threat Dragon threat modeling
kubectl apply -f apps/threat-dragon/application.yaml
```

**Wait for Harbor first** — it creates multiple PVCs on Ceph and takes the longest:

```bash
# Watch Harbor pods come up
kubectl -n harbor get pods -w

# Verify Harbor is accessible
curl -sk https://harbor.knowledgeondemand.net/api/v2.0/health
```

Then verify the rest:

```bash
for ns in harbor openvas faraday metasploit threat-dragon; do
  echo "=== $ns ==="
  kubectl -n $ns get pods
done
```

> **Note:** OpenVAS takes 15–30 minutes on first boot to sync vulnerability feeds. Check with:
> ```bash
> kubectl -n openvas logs -l app=greenbone -c ospd-openvas --tail=20
> ```

## M8. Deploy Build VM

The Build VM is a Proxmox LXC container with Docker CE for building container images.

```bash
cd build-vm
chmod +x deploy-lxc.sh
./deploy-lxc.sh
```

The script prompts for:
- Proxmox API token
- Proxmox SSH password
- LXC root password
- `deploy` user password (for SSH access)
- GitHub SSH key path (auto-detects common locations)
- Kubeconfig path (for creating Harbor pull secrets in K8s)

| Setting | Value |
|---------|-------|
| VMID | 201 |
| IP | 10.83.3.191 |
| Cores / RAM / Disk | 2 / 4 GB / 50 GB |
| Installed | Docker CE, kubectl, curl, jq, git |

Verify:

```bash
ssh deploy@10.83.3.191
docker info    # should show Docker engine running
```

If the kubeconfig wasn't copied during deployment, copy it now:

```bash
scp ~/.kube/config deploy@10.83.3.191:~/.kube/config
```

## M9. Build and Push Container Images

SSH into the Build VM and build all container images:

```bash
ssh deploy@10.83.3.191
cd /opt/talos-cleanroom
git pull    # ensure latest code
```

### LOKI-RS IOC Scanner

```bash
cd apps/loki
chmod +x build-and-push.sh
./build-and-push.sh
```

This script:
1. Creates the `cleanroom` project in Harbor (idempotent)
2. Creates `harbor-pull-secret` in the `loki-scanner` namespace
3. Builds the LOKI-RS image (`ubuntu:24.04` base + FUSE + SSHFS + CIFS)
4. Pushes to `harbor.knowledgeondemand.net/cleanroom/loki-rs-scanner:v2.10.0`

### Scanning Console

```bash
cd /opt/talos-cleanroom
docker build -f scanning-app/Dockerfile -t harbor.knowledgeondemand.net/cleanroom/scanning-console:latest .
docker push harbor.knowledgeondemand.net/cleanroom/scanning-console:latest
```

### Portal

```bash
cd /opt/talos-cleanroom
docker build -f portal/Dockerfile -t harbor.knowledgeondemand.net/cleanroom/portal:latest .
docker push harbor.knowledgeondemand.net/cleanroom/portal:latest
```

### Verify images + create pull secrets

```bash
curl -sk https://harbor.knowledgeondemand.net/api/v2.0/projects/cleanroom/repositories | jq '.[].name'

for ns in scanning-console portal; do
    kubectl create secret docker-registry harbor-pull-secret \
        --namespace="$ns" \
        --docker-server=harbor.knowledgeondemand.net \
        --docker-username=admin \
        --docker-password=Harbor12345 \
        2>/dev/null || echo "  harbor-pull-secret already exists in $ns"
done
```

## M10. Deploy CleanRoom Database

PostgreSQL 17 backing the Scanning Console:

```bash
kubectl apply -f apps/cleanroom-db/application.yaml

# Wait for ArgoCD to sync, then verify
kubectl -n argocd get application cleanroom-db -w
kubectl -n cleanroom-db rollout status statefulset/cleanroom-db --timeout=300s
kubectl -n cleanroom-db exec statefulset/cleanroom-db -- pg_isready
```

## M11. Deploy Scanning Console

```bash
kubectl apply -f apps/scanning-console/application.yaml

# Wait for ArgoCD to sync, then verify
kubectl -n argocd get application scanning-console -w
kubectl -n scanning-console rollout status deployment/scanning-console --timeout=300s
```

Verify at `https://scan.knowledgeondemand.net`.

## M12. Deploy Unified Portal

```bash
kubectl apply -f apps/portal/application.yaml

# Wait for ArgoCD to sync, then verify
kubectl -n argocd get application portal -w
kubectl -n portal rollout status deployment/portal --timeout=120s
```

Verify at `https://cleanroom.knowledgeondemand.net`.

## M13. Deploy Deployment Console (WebUI)

In the manual path, the WebUI is deployed last since it wasn't used for cluster creation:

```bash
cd webui
chmod +x deploy-lxc.sh
./deploy-lxc.sh
```

| Setting | Value |
|---------|-------|
| VMID | 200 |
| IP | 10.83.3.190 |
| Cores / RAM / Disk | 2 / 2 GB / 20 GB |
| Port | 8000 |
| Installed | Python 3.11, terraform, kubectl, helm, talosctl, talhelper, sops |

Access at `http://10.83.3.190:8000` (login: `admin` / `admin`). The WebUI can still be used for future cluster lifecycle management (teardown, redeploy).

## M14. Apply Network Policies

```bash
kubectl apply -f apps/network-policies/
```

See [apps/network-policies/README.md](apps/network-policies/README.md) for the full policy matrix.

## M15. Post-Deployment Verification

Follow the same verification steps as [A12. Post-Deployment Verification](#a12-post-deployment-verification).

## M16. Change Default Credentials

Follow the same steps as [A13. Change Default Credentials](#a13-change-default-credentials).

---

## CLI Script: DeployCluster.sh

As an alternative to both the WebUI and fully manual steps, `DeployCluster.sh` automates M1–M7 and M10–M12 in a single run:

```bash
./scripts/DeployCluster.sh
```

| Script Step | What |
|-------------|------|
| 1 | Terraform VMs on Proxmox |
| 2 | Talos config generation + encryption |
| 3 | Apply configs + bootstrap cluster |
| 4 | Cluster health verification |
| 5 | kubeconfig retrieval |
| 6 | ArgoCD installation |
| 7 | Infrastructure stack (MetalLB, cert-manager, Traefik, Ceph CSI) |
| 8 | ArgoCD self-management |
| 9 | Apply application secrets |
| 10 | Security tools (Harbor, OpenVAS, Faraday, Metasploit, Threat Dragon) |
| 11 | Network policies |
| 12 | CleanRoom DB + Scanning Console + Portal |

**CLI options:**

| Flag | Effect |
|------|--------|
| `--skip-terraform` | Skip VM provisioning (VMs already exist) |
| `--skip-talos` | Skip Talos config + bootstrap (cluster already running) |
| `--from-step N` | Resume from step N (1–12) |

> **Note:** Script step 12 deploys the Scanning Console and Portal ArgoCD applications. Their pods will be in `ImagePullBackOff` until you build and push images. They auto-recover once images exist in Harbor.

After the script completes, the remaining manual steps are:
1. **M5** — Configure DNS
2. **M8** — Deploy Build VM
3. **M9** — Build and push images (pods auto-recover from ImagePullBackOff)
4. **M13** — Deploy WebUI (optional, for future lifecycle management)
5. **M15** — Post-deployment verification

---

# Troubleshooting

### Terraform cannot connect to Proxmox

- Verify API token in `credentials.auto.tfvars`
- Ensure the API token has `PVEAdmin` or equivalent permissions
- Check network connectivity: `curl -sk https://pve01.knowledgeondemand.net:8006/api2/json`

### VMs created but Talos won't bootstrap

- Verify the Talos ISO is correctly uploaded: `pvesm list cephfs --content iso`
- Check VMs are booting from the ISO (Proxmox console → should see Talos maintenance screen)
- Ensure VLAN 3 is configured on the network bridge
- Run `apply-configs.sh` — it provides diagnostics (ping, port checks, guest agent status)

### ArgoCD app stuck in "Progressing"

```bash
kubectl -n argocd get applications <app-name> -o yaml | grep -A5 status
kubectl -n <namespace> describe pods
kubectl -n <namespace> get events --sort-by=.lastTimestamp
```

### Pods stuck in Pending (no PVC)

Ceph CSI may not be ready:

```bash
kubectl get pods -n ceph-csi
kubectl get storageclass
kubectl describe pvc <pvc-name> -n <namespace>
```

### OpenVAS feeds not syncing

```bash
kubectl -n openvas logs -l app=greenbone -c greenbone-feed-sync --tail=50
```

Feed sync requires internet egress. Check network policies allow it:

```bash
kubectl -n openvas get networkpolicy
```

### Harbor ImagePullBackOff

```bash
# Check the pull secret exists in the namespace
kubectl -n <namespace> get secret harbor-pull-secret

# Recreate if missing
for ns in scanning-console portal loki-scanner; do
    kubectl create secret docker-registry harbor-pull-secret \
        --namespace="$ns" \
        --docker-server=harbor.knowledgeondemand.net \
        --docker-username=admin \
        --docker-password=Harbor12345 \
        2>/dev/null || echo "  already exists in $ns"
done
```

### Scanning Console can't reach tools

Verify network policies and RBAC:

```bash
# Check network policy allows egress
kubectl -n scanning-console get networkpolicy -o yaml

# Check RBAC
kubectl -n scanning-console get rolebindings
kubectl auth can-i exec pods -n openvas --as system:serviceaccount:scanning-console:scanning-console
```

### Deployment Console won't start

```bash
ssh deploy@10.83.3.190
sudo systemctl status deployment-webui
sudo journalctl -u deployment-webui -n 50
```

### Cross-app SSO fails

All three apps must share the same `SECRET_KEY` (used to derive HMAC signing keys for one-time auth codes). Verify the secret values match across:
- Deployment Console: `/opt/deployment-webui/.env` → `SECRET_KEY`
- Scanning Console: K8s secret `scanning-console-credentials` → `secret-key`
- Portal: K8s secret `portal-credentials` → `secret-key`

### General: Check ArgoCD for all app health

```bash
kubectl -n argocd get applications -o custom-columns=\
NAME:.metadata.name,\
SYNC:.status.sync.status,\
HEALTH:.status.health.status
```

---

## Quick Reference: Key Files

| Purpose | Path |
|---------|------|
| Automated CLI deployment | [scripts/DeployCluster.sh](scripts/DeployCluster.sh) |
| Infrastructure stack | [apps/deploy-ingress-stack.sh](apps/deploy-ingress-stack.sh) |
| Talos cluster definition | [cluster/talconfig.yaml](cluster/talconfig.yaml) |
| Talos node variables | [cluster/talenv.yaml](cluster/talenv.yaml) |
| Talos config application | [cluster/apply-configs.sh](cluster/apply-configs.sh) |
| VM Terraform config | [terraform/cluster-create/](terraform/cluster-create/) |
| Secret generation | [scripts/generate-secrets.sh](scripts/generate-secrets.sh) |
| Secret application | [scripts/apply-secrets.sh](scripts/apply-secrets.sh) |
| WebUI LXC deployment | [webui/deploy-lxc.sh](webui/deploy-lxc.sh) |
| Build VM LXC deployment | [build-vm/deploy-lxc.sh](build-vm/deploy-lxc.sh) |
| LOKI image build | [apps/loki/build-and-push.sh](apps/loki/build-and-push.sh) |
| DNS reference | [docs/DNS-MAPPING.md](docs/DNS-MAPPING.md) |
| Network policy reference | [apps/network-policies/README.md](apps/network-policies/README.md) |
| Architecture plan | [docs/vuln-management-plan.md](docs/vuln-management-plan.md) |
| ArgoCD app manifests | [apps/](apps/) (each subdirectory) |
