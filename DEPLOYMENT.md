# Talos CleanRoom — End-to-End Deployment Guide

Complete deployment instructions for standing up the full Talos CleanRoom platform on a fresh Proxmox cluster. This guide covers every step from bare Proxmox to a fully operational security scanning platform.

> **Estimated time:** 2–3 hours (mostly waiting for pods, image builds, and feed syncs).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Workstation Setup](#2-workstation-setup)
3. [Generate Secrets](#3-generate-secrets)
4. [Create Kubernetes VMs (Terraform)](#4-create-kubernetes-vms-terraform)
5. [Bootstrap Talos Kubernetes Cluster](#5-bootstrap-talos-kubernetes-cluster)
6. [Install ArgoCD](#6-install-argocd)
7. [Deploy Infrastructure Stack](#7-deploy-infrastructure-stack)
8. [Configure DNS](#8-configure-dns)
9. [Apply Application Secrets](#9-apply-application-secrets)
10. [Deploy Security Tools](#10-deploy-security-tools)
11. [Apply Network Policies](#11-apply-network-policies)
12. [Deploy Build VM](#12-deploy-build-vm)
13. [Build and Push Container Images](#13-build-and-push-container-images)
14. [Deploy CleanRoom Database](#14-deploy-cleanroom-database)
15. [Deploy Scanning Console](#15-deploy-scanning-console)
16. [Deploy Unified Portal](#16-deploy-unified-portal)
17. [Deploy Deployment Console (WebUI)](#17-deploy-deployment-console-webui)
18. [Post-Deployment Verification](#18-post-deployment-verification)
19. [Change Default Credentials](#19-change-default-credentials)
20. [Troubleshooting](#20-troubleshooting)

---

## 1. Prerequisites

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
- SOPS Age key file at `~/.config/sops/age/keys.txt` (or generate in step 3)
- Cloudflare API token for DNS-01 TLS certificate challenges

---

## 2. Workstation Setup

Clone the repository and check out the deployment branch:

```bash
git clone git@github.com:williamdemarigny/Talos-CleanRoom.git
cd Talos-CleanRoom
git checkout refactor/restructure
```

---

## 3. Generate Secrets

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
- **Threat Dragon** — encryption key, JWT signing + refresh keys

Use `--dry-run` to preview without writing files.

---

## Automated vs Manual Deployment

Steps 1–3 (prerequisites, clone, secrets) must be done manually. After that, you have two paths:

### Option A: Automated (Recommended)

```bash
./scripts/DeployCluster.sh
```

`DeployCluster.sh` automates **steps 4–12** in a single run:

| Step | What |
|------|------|
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

After the script completes, continue with **step 8 (DNS)** then jump to **step 12 (Build VM)** and follow steps 12–17 manually. Steps 4–7, 9–11, and 14–16 are already done.

### Option B: Manual

Follow every step below sequentially. The manual steps are useful for understanding what happens at each stage, debugging, or customizing individual components.

---

## 4. Create Kubernetes VMs (Terraform)

> *Skip if using `DeployCluster.sh` — covered by script steps 1–3.*

### Configure Credentials

```bash
cd terraform/cluster-create
```

Create `credentials.auto.tfvars` (this file is gitignored):

```hcl
proxmox_api_url      = "https://pve01.knowledgeondemand.net:8006"
proxmox_api_token    = "terraform@pve!provider=YOUR-TOKEN-SECRET"
proxmox_ssh_password = "YOUR-PROXMOX-ROOT-PASSWORD"
```

### Review Cluster Configuration

The VM specs are defined in `cluster.auto.tfvars`:

| Node | VMID | Role | Cores | RAM | Disk |
|------|------|------|-------|-----|------|
| talos-CleanRoom-master-01 | 2000 | Control plane | 4 | 24 GB | 30 GB |
| talos-CleanRoom-worker-01 | 3001 | Worker | 4 | 24 GB | 30 GB |
| talos-CleanRoom-worker-02 | 3002 | Worker | 4 | 24 GB | 30 GB |
| talos-CleanRoom-worker-03 | 3003 | Worker | 4 | 24 GB | 30 GB |

Edit `cluster.auto.tfvars` if you need different specs or MAC addresses.

### Deploy VMs

```bash
terraform init
terraform plan    # review what will be created
terraform apply   # confirm with 'yes'
```

This creates 4 VMs on Proxmox booting from the Talos ISO. VMs will be in maintenance mode waiting for configuration.

---

## 5. Bootstrap Talos Kubernetes Cluster

> *Skip if using `DeployCluster.sh` — covered by script steps 1–5.*

### Generate Talos Machine Configs

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

> **Automated path:** `scripts/DeployCluster.sh` automates steps 4–12. See [Automated vs Manual Deployment](#automated-vs-manual-deployment) above.

---

## 6. Install ArgoCD

> *Skip if using `DeployCluster.sh` — covered by script step 6.*

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

ArgoCD is now running but not yet accessible via ingress — that comes after Traefik is deployed in step 7.

---

## 7. Deploy Infrastructure Stack

> *Skip if using `DeployCluster.sh` — covered by script steps 7–8.*

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

---

## 8. Configure DNS

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

See [docs/DNS-MAPPING.md](docs/DNS-MAPPING.md) for the complete IP and DNS reference.

---

## 9. Apply Application Secrets

> *Skip if using `DeployCluster.sh` — covered by script step 9.*

Secrets were generated in Step 3 but not yet applied to the cluster. Decrypt and apply them now (before deploying the apps that reference them):

```bash
# Apply ALL application secrets at once
./scripts/apply-secrets.sh

# Or apply individually
sops -d apps/openvas/secrets.sops.yaml       | kubectl apply -f -
sops -d apps/faraday/secrets.sops.yaml       | kubectl apply -f -
sops -d apps/metasploit/secrets.sops.yaml    | kubectl apply -f -
sops -d apps/traefik/basic-auth-secret.sops.yaml | kubectl apply -f -
sops -d apps/threat-dragon/secrets.sops.yaml | kubectl apply -f -
```

Use `--dry-run` to preview: `./scripts/apply-secrets.sh --dry-run`
Use `--app <name>` to target one app: `./scripts/apply-secrets.sh --app metasploit`

> **Important:** Secrets must exist in the cluster before the pods that reference them start. If a pod starts before its secret is applied, it will enter `CreateContainerConfigError` state. Fix by applying the secret and the pod will auto-recover.

---

## 10. Deploy Security Tools

> *Skip if using `DeployCluster.sh` — covered by script step 10.*

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
# Check all security tool namespaces
for ns in harbor openvas faraday metasploit threat-dragon; do
  echo "=== $ns ==="
  kubectl -n $ns get pods
done
```

> **Note:** OpenVAS takes 15–30 minutes on first boot to sync vulnerability feeds. The `openvas` pod will show as running but scans won't work until feed sync completes. Check with:
> ```bash
> kubectl -n openvas logs -l app=greenbone -c ospd-openvas --tail=20
> ```

---

## 11. Apply Network Policies

> *Skip if using `DeployCluster.sh` — covered by script step 11.*

Apply zero-trust network policies (default-deny per namespace with explicit allow rules):

```bash
kubectl apply -f apps/network-policies/
```

This creates policies for: faraday, openvas, threat-dragon, metasploit, argocd, scanning-console, portal, cleanroom-db.

See [apps/network-policies/README.md](apps/network-policies/README.md) for the full policy matrix.

> **Tip:** If a service stops working after applying policies, temporarily remove the policy for that namespace to confirm it's the cause: `kubectl delete networkpolicy -n <namespace> --all`

---

## 12. Deploy Build VM

The Build VM is a Proxmox LXC container with Docker CE for building and pushing container images.

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

After deployment, verify:

```bash
ssh deploy@10.83.3.191
docker info    # should show Docker engine running
```

---

## 13. Build and Push Container Images

SSH into the Build VM and build all three container images:

```bash
ssh deploy@10.83.3.191
cd /opt/talos-cleanroom
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

Verify all images are in Harbor:

```bash
curl -sk https://harbor.knowledgeondemand.net/api/v2.0/projects/cleanroom/repositories | jq '.[].name'
```

Expected: `cleanroom/loki-rs-scanner`, `cleanroom/scanning-console`, `cleanroom/portal`.

---

## 14. Deploy CleanRoom Database

> *Skip if using `DeployCluster.sh` — covered by script step 12.*

PostgreSQL 17 backing the Scanning Console:

```bash
kubectl apply -f apps/cleanroom-db/application.yaml
```

Wait for the StatefulSet:

```bash
kubectl -n cleanroom-db rollout status statefulset/cleanroom-db --timeout=300s
```

Verify:

```bash
kubectl -n cleanroom-db exec statefulset/cleanroom-db -- pg_isready
```

The database includes:
- A daily backup CronJob at 02:00 UTC (`pg_dump | gzip`)
- 14-day backup retention
- Readiness/liveness probes via `pg_isready`

---

## 15. Deploy Scanning Console

> *Skip if using `DeployCluster.sh` — covered by script step 12.*

The Scanning Console provides vulnerability scanning (Nmap, OpenVAS, Metasploit, LOKI-RS IOC) with PostgreSQL persistence:

```bash
kubectl apply -f apps/scanning-console/application.yaml
```

The deployment includes an init container that runs Alembic database migrations before the app starts.

Wait for it:

```bash
kubectl -n scanning-console rollout status deployment/scanning-console --timeout=300s
```

Verify at `https://scan.knowledgeondemand.net`.

---

## 16. Deploy Unified Portal

> *Skip if using `DeployCluster.sh` — covered by script step 12.*

The Portal is the landing page providing SSO across all three applications:

```bash
kubectl apply -f apps/portal/application.yaml
```

Wait for it:

```bash
kubectl -n portal rollout status deployment/portal --timeout=120s
```

Verify at `https://cleanroom.knowledgeondemand.net`.

---

## 17. Deploy Deployment Console (WebUI)

The Deployment Console runs in a Proxmox LXC container and provides a web UI for cluster lifecycle management:

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

After deployment:

```bash
# Verify the service is running
ssh deploy@10.83.3.190
sudo systemctl status deployment-webui
```

Access at `http://10.83.3.190:8000` (login: `admin` / `admin`).

---

## 18. Post-Deployment Verification

### Service Access Points

| Service | URL | Default Credentials |
|---------|-----|-------------------|
| ArgoCD | `https://argocd.knowledgeondemand.net` | admin / (see step 6) |
| Harbor | `https://harbor.knowledgeondemand.net` | admin / Harbor12345 |
| OpenVAS | `https://openvas.knowledgeondemand.net` | admin / admin |
| Faraday | `https://faraday.knowledgeondemand.net` | admin / (k8s secret) |
| Threat Dragon | `https://threatdragon.knowledgeondemand.net` | — (no auth) |
| Traefik Dashboard | `https://traefik.knowledgeondemand.net` | admin / (generated) |
| Scanning Console | `https://scan.knowledgeondemand.net` | admin / admin |
| Portal | `https://cleanroom.knowledgeondemand.net` | admin / admin |
| Deployment Console | `http://10.83.3.190:8000` | admin / admin |

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

---

## 19. Change Default Credentials

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

## 20. Troubleshooting

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

# Recreate if missing (from Build VM)
ssh deploy@10.83.3.191
cd /opt/talos-cleanroom/apps/loki
./build-and-push.sh    # also creates pull secrets
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

---

## Deployment Order Summary

```
Proxmox Cluster (online)
    │
    ├─ [3]  generate-secrets.sh          → SOPS-encrypted K8s secrets
    │
    │  ┌─── DeployCluster.sh automates steps 4–11, 14–16 ───┐
    │  │                                                      │
    ├─ [4]  terraform apply              → 4 Talos VMs        │
    ├─ [5]  talhelper + apply-configs.sh → K8s bootstrapped   │
    ├─ [6]  ArgoCD install               → GitOps controller  │
    ├─ [7]  deploy-ingress-stack.sh      → MetalLB, certs,    │
    │  │                                    Traefik, Ceph CSI  │
    ├─ [9]  apply-secrets.sh             → App secrets to K8s  │
    ├─ [10] Security tool ArgoCD apps    → Harbor, OpenVAS,    │
    │  │                                    Faraday, etc.      │
    ├─ [11] Network policies             → Zero-trust          │
    ├─ [14] CleanRoom DB                 → PostgreSQL 17       │
    ├─ [15] Scanning Console             → Scanning web app    │
    ├─ [16] Portal                       → SSO landing page    │
    │  │                                                      │
    │  └──────────────────────────────────────────────────────┘
    │
    ├─ [8]  DNS records                  → *.knowledgeondemand.net (manual)
    ├─ [12] Build VM LXC                 → Docker build environment (manual)
    ├─ [13] Image builds                 → LOKI-RS, scanning-console, portal (manual)
    └─ [17] Deployment Console LXC       → Cluster lifecycle web UI (manual)
```
