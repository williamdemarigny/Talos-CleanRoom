# Talos CleanRoom - Proxmox Kubernetes Security Platform

A complete Infrastructure-as-Code (IaC) solution for provisioning a Talos Kubernetes cluster on Proxmox, with an integrated security toolchain and web-based management. Everything is GitOps-managed via ArgoCD.

## Overview

Talos CleanRoom deploys a hardened Kubernetes cluster on Proxmox with a full suite of vulnerability scanning and security tools. The platform is split into three independent web applications — a Deployment Console for cluster lifecycle, a Scanning Console for vulnerability management, and a Unified Portal for cross-app SSO — backed by PostgreSQL and managed through ArgoCD.

**Key Features:**

- **3-App Architecture**: Deployment Console (LXC), Scanning Console (K8s), Portal (K8s) with shared SSO
- **Security Toolchain**: OpenVAS, Metasploit, Faraday, LOKI-RS IOC scanner, OWASP Threat Dragon
- **Private Container Registry**: Self-hosted Harbor with Trivy vulnerability scanning
- **Automated Provisioning**: Terraform VMs, Talos bootstrap, ArgoCD GitOps, SOPS-encrypted secrets
- **Zero-Trust Networking**: Default-deny network policies per namespace
- **Ceph Storage**: Persistent volumes via Proxmox-managed Ceph RBD

## Architecture

```
Proxmox Cluster (4 nodes: pve01-04, 10.83.2.20-23)
  |
  +-- Talos K8s Cluster (VLAN 3: 10.83.3.0/24)
  |     +-- Control Plane: master-01 (VMID 2000, 10.83.3.10)
  |     +-- Workers: worker-01..03 (VMIDs 3001-3003, 10.83.3.15-17)
  |     +-- Pod CIDR: 10.14.0.0/16, Service CIDR: 10.15.0.0/16
  |     +-- Storage: Ceph RBD (4 monitors), MetalLB: 10.83.3.200-250
  |     |
  |     +-- Infrastructure (ArgoCD-managed)
  |     |     MetalLB, cert-manager, Traefik, Ceph CSI, Metrics Server
  |     |
  |     +-- Security Tools (ArgoCD-managed)
  |     |     OpenVAS, Faraday, Metasploit, Harbor, Threat Dragon
  |     |
  |     +-- Platform Apps (ArgoCD-managed)
  |           CleanRoom DB (PostgreSQL 17)
  |           Scanning Console (scan.knowledgeondemand.net)
  |           Portal (cleanroom.knowledgeondemand.net)
  |
  +-- LXC: Deployment Console (VMID 200, 10.83.3.190)
  +-- LXC: Build VM (VMID 201, 10.83.3.191)
```

**Ingress path:** Internet -> MetalLB (10.83.3.200) -> Traefik -> K8s Services
**DNS:** All services at `*.knowledgeondemand.net`, wildcard cert via cert-manager + Cloudflare DNS-01

## Applications

| Application | Location | Purpose |
|------------|----------|---------|
| **Deployment Console** | LXC (10.83.3.190:8000) | Cluster lifecycle management (Terraform, Talos, ArgoCD) |
| **Scanning Console** | K8s (`scan.knowledgeondemand.net`) | Nmap, OpenVAS, Metasploit, LOKI-RS scanning + Faraday integration |
| **Portal** | K8s (`cleanroom.knowledgeondemand.net`) | Landing page with one-time-code SSO across all apps |
| **CleanRoom DB** | K8s (cleanroom-db namespace) | PostgreSQL 17 shared database for Scanning Console |

All three apps share a common `SECRET_KEY` for cross-app SSO via HMAC-signed one-time auth codes.

## Project Structure

```
Talos-CleanRoom/
+-- DEPLOYMENT.md                       # End-to-end deployment guide
|
+-- apps/                               # ArgoCD-managed K8s applications
|   +-- argocd/                         # Self-managing (Helm, HA 2x replicas)
|   +-- metallb/                        # L2 load balancer (10.83.3.200-250)
|   +-- cert-manager/                   # TLS (Cloudflare DNS-01)
|   +-- traefik/                        # Ingress controller (fixed LB .200)
|   +-- ceph-storage/                   # Ceph CSI RBD StorageClass
|   +-- metrics-server/                 # HPA support
|   +-- harbor/                         # Container registry (Trivy scanning)
|   +-- openvas/                        # Greenbone vulnerability scanner
|   +-- faraday/                        # Vulnerability management
|   +-- metasploit/                     # Penetration testing framework
|   +-- threat-dragon/                  # OWASP threat modeling
|   +-- loki/                           # LOKI-RS IOC scanner image + build script
|   +-- cleanroom-db/                   # PostgreSQL 17 StatefulSet + backup CronJob
|   +-- scanning-console/              # Scanning Console K8s manifests
|   +-- portal/                         # Portal K8s manifests
|   +-- network-policies/              # Zero-trust namespace isolation
|   +-- securecodebox/                  # Automated scanning framework
|   +-- deploy-ingress-stack.sh         # 13-step infrastructure deployment
|
+-- scanning-app/                       # Scanning Console source (FastAPI)
+-- portal/                             # Portal source (FastAPI)
+-- webui/                              # Deployment Console source (FastAPI, runs in LXC)
+-- lib/talos-common/                   # Shared Python library (auth, config, base services)
|
+-- cluster/                            # Talos Linux configuration
|   +-- talconfig.yaml                  # Cluster definition (v1.12.2, K8s v1.32.3)
|   +-- talenv.yaml                     # Node names, IPs, MACs
|   +-- talsecret.sops.yaml             # SOPS-encrypted cluster secrets
|   +-- apply-configs.sh                # DHCP discovery + config application
|
+-- terraform/                          # Proxmox provisioning
|   +-- cluster-create/                 # Talos VMs (4 nodes)
|   +-- webui-lxc/                      # Deployment Console LXC
|   +-- build-lxc/                      # Build VM LXC
|   +-- modules/proxmox-lxc/            # Reusable LXC module
|
+-- scripts/                            # Orchestration
|   +-- DeployCluster.sh                # Automated CLI deployment
|   +-- generate-secrets.sh             # SOPS secret generation (9 apps)
|   +-- apply-secrets.sh                # Decrypt + apply secrets to K8s
|   +-- tfvars-to-talos-env.sh          # Terraform -> talenv.yaml
|
+-- build-vm/                           # Build VM LXC (Docker CE for image builds)
+-- lib/                                # Shared bash utilities
+-- docs/                               # DNS mapping, architecture plan
```

## Prerequisites

### Required Tools
| Tool | Version | Purpose |
|------|---------|---------|
| Terraform | >= 1.7 | Infrastructure provisioning |
| talhelper | latest | Talos configuration generator |
| talosctl | latest | Talos cluster management |
| kubectl | >= 1.29 | Kubernetes CLI |
| helm | >= 3.x | Kubernetes package manager |
| sops | >= 3.8 | Secret encryption (with Age) |
| age | latest | Encryption key generation |
| jq | any | JSON processing |
| git | any | Repository access |

### Infrastructure
- Proxmox VE 7.x or 8.x cluster (4 nodes) with API token
- Ceph storage pool configured
- VLAN 3 on `vmbr0` (10.83.3.0/24)
- Talos ISO uploaded: `cephfs:iso/metal-amd64.iso`
- Debian 12 LXC template available
- Cloudflare API token for DNS-01 TLS challenges

### Network
| Resource | IP / Range |
|----------|-----------|
| Control plane | 10.83.3.10 |
| Workers | 10.83.3.15-17 |
| MetalLB pool | 10.83.3.200-250 |
| Deployment Console | 10.83.3.190 |
| Build VM | 10.83.3.191 |

## Deployment

For complete step-by-step deployment instructions, see **[DEPLOYMENT.md](DEPLOYMENT.md)**.

### Quick Start (WebUI — Recommended)

```bash
# 1. Clone repo
git clone git@github.com:williamdemarigny/Talos-CleanRoom.git
cd Talos-CleanRoom
git checkout refactor/restructure

# 2. Deploy the WebUI LXC container
cd webui && ./deploy-lxc.sh

# 3. Open http://10.83.3.190:8000, login, click "Deploy"
#    All 23 steps run automatically — secrets, Build VM, images, apps, network policies

# 4. Configure DNS: *.knowledgeondemand.net → Traefik LB IP (10.83.3.200)
```

### Quick Start (CLI)

```bash
# 1. Clone and generate secrets
git clone git@github.com:williamdemarigny/Talos-CleanRoom.git
cd Talos-CleanRoom
git checkout refactor/restructure
./scripts/generate-secrets.sh

# 2. Automated deployment (Terraform -> Talos -> ArgoCD -> infra -> security tools)
./scripts/DeployCluster.sh

# 3. Apply secrets and deploy remaining apps (see DEPLOYMENT.md for manual steps)
./scripts/apply-secrets.sh
```

### What DeployCluster.sh Automates

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
| 10 | Security tools (OpenVAS, Faraday, Metasploit, Threat Dragon, Harbor) |
| 11 | Network policies |
| 12 | CleanRoom DB, Scanning Console, Portal |

### What Requires Manual Steps

**WebUI (automated) path — only 2 manual steps after clicking Deploy:**
- **Deployment Console** — `webui/deploy-lxc.sh` (one-time LXC setup, before deploying)
- **DNS configuration** — create `*.knowledgeondemand.net` wildcard A record (after Traefik is up)

**CLI path — additional manual steps:**
- **Build VM** — `build-vm/deploy-lxc.sh` (interactive Proxmox prompts)
- **Image builds** — SSH to Build VM, run `build-and-push.sh` for LOKI-RS, Scanning Console, Portal

## Accessing Services

| Service | URL | Default Credentials |
|---------|-----|---------------------|
| Portal | https://cleanroom.knowledgeondemand.net | admin / admin |
| Scanning Console | https://scan.knowledgeondemand.net | admin / admin |
| Deployment Console | http://10.83.3.190:8000 | admin / admin |
| ArgoCD | https://argocd.knowledgeondemand.net | admin / admin |
| Harbor | https://harbor.knowledgeondemand.net | admin / Harbor12345 |
| OpenVAS | https://openvas.knowledgeondemand.net | admin / admin |
| Faraday | https://faraday.knowledgeondemand.net | admin / (k8s secret) |
| Traefik | https://traefik.knowledgeondemand.net | admin / (generated) |
| Threat Dragon | https://threatdragon.knowledgeondemand.net | (no auth) |
| Metasploit | `kubectl exec -n metasploit deploy/metasploit -c metasploit -- ./msfconsole` | CLI |

> **Change all default passwords before production use.** See [DEPLOYMENT.md — Change Default Credentials](DEPLOYMENT.md#a5-change-default-credentials).

## Troubleshooting

See [DEPLOYMENT.md — Troubleshooting](DEPLOYMENT.md#troubleshooting) for detailed troubleshooting.

Common issues:
- **OpenVAS OOMKill** — ospd-openvas needs 4Gi memory limit (not 1Gi)
- **OpenVAS feeds** — first sync takes 30-60 minutes
- **Harbor 404** — IngressRoute must point to `harbor` service, not `harbor-core`
- **LOKI pod Forbidden** — `loki-scanner` namespace needs `pod-security.kubernetes.io/enforce=privileged` label
- **Cross-app SSO fails** — all 3 apps must share the same `SECRET_KEY`

## References

- [Talos Linux](https://www.talos.dev/)
- [Proxmox Terraform Provider](https://registry.terraform.io/providers/bpg/proxmox/latest/docs)
- [talhelper](https://github.com/budimanjojo/talhelper)
- [SOPS](https://github.com/getsops/sops)
- [ArgoCD](https://argo-cd.readthedocs.io/)
- [Harbor](https://goharbor.io/docs/)
- [OpenVAS / Greenbone](https://greenbone.github.io/docs/)
- [Faraday](https://docs.faradaysec.com/)
- [LOKI-RS IOC Scanner](https://github.com/Neo23x0/Loki-RS)
- [SecureCodeBox](https://www.securecodebox.io/)
