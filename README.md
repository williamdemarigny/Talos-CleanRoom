# Talos CleanRoom - Proxmox Kubernetes Security Platform

A complete Infrastructure-as-Code (IaC) solution for provisioning a Talos Kubernetes cluster on Proxmox, deploying an integrated security toolchain, and managing it all through a web-based deployment UI.

## Overview

This project provides automated deployment and lifecycle management of a Talos Kubernetes cluster across a Proxmox cluster, with a full suite of security scanning and vulnerability management tools. Everything is managed via GitOps (ArgoCD) and deployed through either the Web UI or CLI scripts.

**Key Features:**

- **Web-Based Deployment UI**: FastAPI application for one-click cluster provisioning and security scanning
- **DNS/FQDN-Based Deployment**: Infrastructure configuration using DNS names for portability and flexibility
- **Security Toolchain**: OpenVAS, Metasploit, Faraday, SecureCodeBox, LOKI-RS IOC scanner
- **Private Container Registry**: Self-hosted Harbor with Trivy vulnerability scanning
- **Cluster Provisioning**: Deploy Talos VMs across your Proxmox cluster with automatic node distribution
- **Talos Configuration Management**: Automated config generation with talhelper and SOPS-encrypted secrets
- **GitOps Ready**: ArgoCD-based application deployment with automated sync and self-management
- **Ceph Storage**: Persistent volumes via Proxmox-managed Ceph RBD

## Environment Architecture

```
                                   ┌─────────────────────────────────────────────────────────────────┐
                                   │                       PROXMOX CLUSTER                           │
                                   │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐│
                                   │  │   pve01     │ │   pve02     │ │   pve03     │ │   pve04     ││
                                   │  │ 10.83.2.20  │ │ 10.83.2.21  │ │ 10.83.2.22  │ │ 10.83.2.23  ││
                                   │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘│
                                   └─────────────────────────────────────────────────────────────────┘
                                                               │
                          ┌────────────────────────────────────┴────────────────────────────────────┐
                          │                         VLAN 3 - 10.83.3.0/24                           │
                          │                           Gateway: 10.83.3.1                            │
                          └────────────────────────────────────┬────────────────────────────────────┘
                                                               │
         ┌─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────┐
         │                                                     │                                                     │
┌────────┴────────┐                              ┌─────────────┴─────────────┐                     ┌─────────────────┴─────────────────┐
│ LXC CONTAINERS  │                              │     TALOS KUBERNETES      │                     │      METALLB IP POOL              │
├─────────────────┤                              │         CLUSTER           │                     │    10.83.3.200 - 10.83.3.250      │
│ deployment-webui│                              ├───────────────────────────┤                     └───────────────────────────────────┘
│ VMID: 200       │                              │                           │
│ IP: 10.83.3.190 │                              │  ┌─────────────────────┐  │
├─────────────────┤                              │  │   CONTROL PLANE     │  │
│ build-vm        │                              │  │   master-01         │  │
│ VMID: 201       │                              │  │   VMID: 2000        │  │
│ IP: 10.83.3.191 │                              │  │   IP: 10.83.3.10    │  │
└─────────────────┘                              │  │   4 CPU / 8GB RAM   │  │
                                                 │  └─────────────────────┘  │
┌─────────────────┐                              │                           │
│ OPNSENSE FW     │                              │  ┌─────────────────────┐  │
├─────────────────┤                              │  │    WORKER NODES     │  │
│ opnsense-fw-01  │                              │  ├─────────────────────┤  │
│ VMID: 1010      │                              │  │ worker-01 (3001)    │  │
│ IP: 10.83.3.5   │                              │  │ worker-02 (3002)    │  │
├─────────────────┤                              │  │ worker-03 (3003)    │  │
│ opnsense-fw-02  │                              │  │ IPs: 10.83.3.15-17  │  │
│ VMID: 1011      │                              │  │ 4 CPU / 8GB / +30G  │  │
│ IP: 10.83.3.6   │                              │  └─────────────────────┘  │
└─────────────────┘                              └───────────────────────────┘

                             ┌──────────────────────────────────────────────────────────┐
                             │                 KUBERNETES NETWORK                       │
                             │  Pod Network:     10.14.0.0/16                           │
                             │  Service Network: 10.15.0.0/16                           │
                             │  Storage:         Ceph RBD (Proxmox-managed)             │
                             └──────────────────────────────────────────────────────────┘

                             ┌──────────────────────────────────────────────────────────┐
                             │                 DEPLOYED SERVICES                        │
                             ├──────────────────────────────────────────────────────────┤
                             │  ArgoCD        → https://argocd.knowledgeondemand.net    │
                             │  Traefik       → https://traefik.knowledgeondemand.net   │
                             │  Harbor        → https://harbor.knowledgeondemand.net    │
                             │  OpenVAS       → https://openvas.knowledgeondemand.net   │
                             │  Faraday       → https://faraday.knowledgeondemand.net   │
                             │  Threat Dragon → https://threatdragon.knowledgeondemand  │
                             │  Metasploit    → kubectl exec (msfconsole)               │
                             │  SecureCodeBox → Automated security scanning             │
                             │  LOKI-RS       → IOC scanning (via WebUI)                │
                             │  MetalLB       → Load Balancer (L2 Mode)                 │
                             │  cert-manager  → TLS Certificate Management              │
                             └──────────────────────────────────────────────────────────┘
```

## Project Structure

```
Talos-CleanRoom/
├── README.md                           # This file
├── LICENSE                             # Project license
│
├── apps/                               # ArgoCD-managed Kubernetes applications
│   ├── argocd/                         # ArgoCD self-management + credentials
│   │   ├── application.yaml
│   │   ├── install.sh / uninstall.sh
│   │   ├── values.yaml
│   │   └── repo-credentials.sops.yaml
│   ├── ceph-storage/                   # Ceph CSI RBD storage integration
│   │   ├── application.yaml
│   │   ├── ceph-csi-secret.sops.yaml
│   │   └── storageclass.yaml
│   ├── metallb/                        # L2 load balancer
│   ├── cert-manager/                   # TLS certificates
│   ├── traefik/                        # Ingress controller
│   ├── metrics-server/                 # Kubernetes metrics
│   ├── harbor/                         # Private container registry
│   ├── openvas/                        # Vulnerability scanner
│   ├── faraday/                        # Vulnerability management
│   ├── metasploit/                     # Penetration testing
│   ├── securecodebox/                  # Automated security scanning
│   ├── threat-dragon/                  # Threat modeling
│   ├── loki/                           # LOKI-RS IOC scanner image
│   ├── network-policies/               # Zero-trust namespace isolation
│   └── deploy-ingress-stack.sh         # Infrastructure stack deployment
│
├── cluster/                            # Talos Linux cluster configuration
│   ├── talconfig.yaml                  # Talos cluster definition
│   ├── talsecret.sops.yaml             # Encrypted secrets
│   ├── talenv.yaml                     # Environment variables
│   ├── apply-configs.sh                # Config application + bootstrap
│   └── clusterconfig/                  # Generated machine configs
│
├── webui/                              # Web UI for deployment + security scanning
│   ├── README.md                       # Web UI deployment guide
│   ├── README-TECHNICAL.md             # Technical architecture docs
│   ├── deploy-lxc.sh                   # Automated LXC deployment
│   ├── app/                            # FastAPI application
│   │   ├── models/                     # Pydantic data models
│   │   ├── routers/                    # API endpoints + WebSocket handlers
│   │   └── services/                   # Business logic + shared utilities
│   ├── templates/                      # Jinja2 HTML templates + components
│   ├── static/                         # CSS, JS assets + shared utilities
│   └── scripts/                        # Container setup scripts
│
├── build-vm/                           # Docker image build VM (LXC)
│   ├── README.md                       # Build VM deployment guide
│   ├── deploy-lxc.sh                   # Automated LXC deployment
│   └── scripts/                        # Container setup (Docker CE, kubectl)
│
├── terraform/                          # All Terraform configurations
│   ├── cluster-create/                 # Talos cluster VMs on Proxmox
│   │   ├── main.tf, variables.tf, locals.tf
│   │   ├── cluster.auto.tfvars
│   │   └── credentials.auto.tfvars    # (gitignored)
│   ├── webui-lxc/                      # WebUI LXC container
│   ├── build-lxc/                      # Build VM LXC container
│   └── modules/
│       └── proxmox-lxc/               # Shared LXC container module
│
├── scripts/                            # Orchestration & utility scripts
│   ├── DeployCluster.sh               # CLI deployment orchestrator
│   ├── deployment_tui.py              # Terminal UI for deployment
│   ├── check_network.py              # Network validation
│   ├── generate-secrets.sh           # SOPS secret generation
│   └── tfvars-to-talos-env.sh        # Terraform → Talos env conversion
│
├── lib/                                # Shared bash utilities
│   ├── functions.sh                   # Common functions (wait_for_deployment, etc.)
│   └── lxc-deploy-common.sh           # Shared LXC deployment functions
│
└── docs/                               # Documentation
    └── DNS-MAPPING.md                 # DNS to IP address reference
```

## Prerequisites

### Required Tools
| Tool | Version | Purpose |
|------|---------|---------|
| Terraform | >= 1.14.6 | Infrastructure provisioning |
| talhelper | v3.1.5+ | Talos configuration generator |
| talosctl | v1.12.4+ | Talos CLI tool |
| SOPS | v3.12.1+ | Secrets encryption (with Age) |
| age | v1.3.1+ | Age encryption backend for SOPS |
| jq | v1.8.1+ | JSON processor for scripts |
| curl | - | HTTP requests |
| helm | v3.17+ | Kubernetes package manager |
| kubectl | v1.32+ | Kubernetes CLI (match cluster version) |

### Infrastructure Requirements
- **Proxmox VE** cluster with API access and valid API token
- **Talos ISO** uploaded to Proxmox storage (`metal-amd64.iso`)
- **Ceph** storage pool configured on Proxmox (for Kubernetes PVs)
- **OPNSense Template VM** (optional, for firewall deployment)

### Network Prerequisites
- **Network**: 10.83.3.0/24 (VLAN 3)
- **Gateway**: 10.83.3.1
- **DNS Server**: Configured with all required A records (see below)
- **Network Access**: Workstation must resolve and reach all FQDNs

## DNS Records Required

### Proxmox Cluster Nodes
| FQDN | IP Address |
|------|------------|
| pve01.knowledgeondemand.net | 10.83.2.20 |
| pve02.knowledgeondemand.net | 10.83.2.21 |
| pve03.knowledgeondemand.net | 10.83.2.22 |
| pve04.knowledgeondemand.net | 10.83.2.23 |

### OPNsense Firewall VMs
| FQDN | IP Address |
|------|------------|
| opnsense-fw-01.knowledgeondemand.net | 10.83.3.5 |
| opnsense-fw-02.knowledgeondemand.net | 10.83.3.6 |

### Talos Kubernetes Cluster
| FQDN | IP Address |
|------|------------|
| talos-CleanRoom-master-01.knowledgeondemand.net | 10.83.3.10 |
| talos-CleanRoom-worker-01.knowledgeondemand.net | 10.83.3.15 |
| talos-CleanRoom-worker-02.knowledgeondemand.net | 10.83.3.16 |
| talos-CleanRoom-worker-03.knowledgeondemand.net | 10.83.3.17 |

### Kubernetes Services (via Traefik LoadBalancer)

All services resolve to the Traefik MetalLB IP (from the 10.83.3.200-250 pool).

| FQDN | Service |
|------|---------|
| traefik.knowledgeondemand.net | Traefik Dashboard |
| argocd.knowledgeondemand.net | ArgoCD UI |
| harbor.knowledgeondemand.net | Harbor Container Registry |
| openvas.knowledgeondemand.net | OpenVAS Vulnerability Scanner |
| faraday.knowledgeondemand.net | Faraday Vulnerability Management |
| threatdragon.knowledgeondemand.net | OWASP Threat Dragon |

## Virtual Machines

### OPNsense Firewall VMs
| Name | VMID | MAC | Cores | Memory | Disk |
|------|------|-----|-------|--------|------|
| opnsense-fw-01 | 1010 | BC:24:21:F1:00:01 | 2 | 8GB | 30G |
| opnsense-fw-02 | 1011 | BC:24:21:F1:00:02 | 2 | 8GB | 30G |

### Talos Kubernetes Cluster
| Name | VMID | Role | MAC | Cores | Memory | Disks |
|------|------|------|-----|-------|--------|-------|
| talos-CleanRoom-master-01 | 2000 | Control Plane | BC:24:21:A4:B2:97 | 4 | 8GB | 30G |
| talos-CleanRoom-worker-01 | 3001 | Worker | BC:24:21:4C:99:A1 | 4 | 8GB | 30G + 30G |
| talos-CleanRoom-worker-02 | 3002 | Worker | BC:24:21:4C:99:A2 | 4 | 8GB | 30G + 30G |
| talos-CleanRoom-worker-03 | 3003 | Worker | BC:24:21:4C:99:A3 | 4 | 8GB | 30G + 30G |

### LXC Containers
| Name | VMID | Purpose | IP | Cores | Memory | Disk |
|------|------|---------|----|-------|--------|------|
| deployment-webui | 200 | Web UI for deployment + scanning | 10.83.3.190 | 2 | 2GB | 20G |
| build-vm | 201 | Docker image builds for Harbor | 10.83.3.191 | 2 | 4GB | 50G |

## Deployment Workflow

### Option A: Web UI (Recommended)

The Web UI automates the full cluster deployment (17 steps: Terraform VMs, Talos bootstrap, ArgoCD, infrastructure stack, security tools including Harbor, and integration configuration). The LOKI-RS IOC scanner image requires an additional post-deployment build step.

#### Phase 1: Deploy the WebUI LXC Container

```bash
cd webui
./deploy-lxc.sh
```

Follow the prompts for Proxmox credentials, SSH key, and SOPS age key. Once complete, access the UI at `http://10.83.3.190:8000`.

See [webui/README.md](webui/README.md) for details.

#### Phase 2: Deploy the Cluster via WebUI

1. Log in with `admin` / `admin`
2. Go to **Configuration** and verify Terraform/Talos settings
3. Go to **Deployment** and click **Start Deployment**
4. The 17-step process runs automatically:
   - Steps 0-1: Validate git repo and dependencies
   - Steps 2-3: Terraform creates Proxmox VMs, waits for boot
   - Steps 4-5: Generate and apply Talos machine configs, bootstrap etcd
   - Steps 6-7: Verify cluster health, export kubeconfig
   - Step 8: Install ArgoCD
   - Step 9: Deploy infrastructure stack (MetalLB, cert-manager, Traefik, Ceph CSI)
   - Step 10: Enable ArgoCD self-management
   - Steps 11-15: Deploy OpenVAS, Faraday, Metasploit, Threat Dragon, Harbor
   - Step 16: Configure integrations (Faraday workspace, cross-service connectivity)

#### Phase 3: Configure DNS

After deployment, get the Traefik LoadBalancer IP:

```bash
kubectl get svc traefik -n traefik
# EXTERNAL-IP will be from the MetalLB pool (10.83.3.200-250)
```

Create DNS A records pointing to that IP for all services:

| FQDN | Purpose |
|------|---------|
| traefik.knowledgeondemand.net | Traefik Dashboard |
| argocd.knowledgeondemand.net | ArgoCD UI |
| harbor.knowledgeondemand.net | Harbor Container Registry |
| openvas.knowledgeondemand.net | OpenVAS Scanner |
| faraday.knowledgeondemand.net | Faraday Vulnerability Management |
| threatdragon.knowledgeondemand.net | OWASP Threat Dragon |

#### Phase 4: Deploy Build VM and LOKI-RS Image

The build VM is required for building the LOKI-RS IOC scanner image and pushing it to Harbor.

```bash
cd build-vm
./deploy-lxc.sh
```

Follow the prompts for Proxmox credentials, SSH key, and kubeconfig path. Once deployed, wait for Harbor to be healthy, then build and push the image:

```bash
ssh deploy@10.83.3.191
cd /opt/talos-cleanroom/apps/loki
HARBOR_PASSWORD="<your-harbor-password>" bash build-and-push.sh
```

The script creates the Harbor `cleanroom` project, sets up `harbor-pull-secret` in the `loki-scanner` namespace, builds the image, and pushes it.

#### Phase 5: Create Traefik Basic Auth Secret

```bash
# Generate password hash (install apache2-utils if needed)
htpasswd -nb admin YOUR_SECURE_PASSWORD

# Create the secret for Traefik dashboard authentication
kubectl create secret generic basic-auth-secret --from-literal=users='admin:<hash>' -n traefik
```

#### Phase 6: Verify Full Deployment

```bash
# All namespaces should show pods Running
kubectl get pods -A

# All ArgoCD applications should be Synced/Healthy
kubectl get applications -n argocd

# Ingress routes should be configured
kubectl get ingressroute -A
```

**Note:** OpenVAS feed synchronization takes 30-60 minutes on first deployment. Scans will be incomplete until feeds are fully loaded.

---

### Option B: CLI Deployment

#### Step 1: Deploy Infrastructure with Terraform

```bash
cd "$(git rev-parse --show-toplevel)/terraform/cluster-create"
terraform init
terraform plan -out=".tfplan"
terraform apply ".tfplan"
```

#### Step 2: Generate Talos Configuration

```bash
cd "$(git rev-parse --show-toplevel)"
./scripts/tfvars-to-talos-env.sh

cd cluster
export SOPS_AGE_KEY_FILE=$HOME/.config/sops/age/keys.txt
talhelper gensecret > talsecret.sops.yaml
sops -e -i talsecret.sops.yaml
talhelper genconfig --env-file talenv.yaml
```

#### Step 3: Apply Talos Configs and Bootstrap
```bash
cd "$(git rev-parse --show-toplevel)/cluster"
export TALOSCONFIG=$(pwd)/clusterconfig/talosconfig

# Apply configs and bootstrap (waits 180s then bootstraps automatically)
./apply-configs.sh --bootstrap

# Wait for cluster health
talosctl health --nodes=talos-CleanRoom-master-01.knowledgeondemand.net

# Get kubeconfig
talosctl kubeconfig --nodes=talos-CleanRoom-master-01.knowledgeondemand.net ~/.kube/config
```

#### Step 4: Verify Cluster

```bash
kubectl get nodes
kubectl get pods -A
```

#### Step 5: Configure Private Repository Access (Optional)

If your repository is private, configure ArgoCD with SSH deploy key credentials:

```bash
# Generate SSH deploy key
ssh-keygen -t ed25519 -C "argocd-deploy-key" -f ~/.ssh/argocd_deploy_key -N ""

# Add public key to GitHub: Repo → Settings → Deploy keys
cat ~/.ssh/argocd_deploy_key.pub

# Edit credentials template with your private key
cd "$(git rev-parse --show-toplevel)/apps/argocd"
# Edit repo-credentials.yaml - paste private key from: cat ~/.ssh/argocd_deploy_key

# Encrypt with SOPS
sops --config ../../cluster/.sops.yaml --encrypt repo-credentials.yaml > repo-credentials.sops.yaml
rm repo-credentials.yaml  # Delete unencrypted file
```

#### Step 6: Install ArgoCD

```bash
cd "$(git rev-parse --show-toplevel)/apps/argocd"
./install.sh

# Verify ArgoCD is running
kubectl get pods -n argocd

# Verify repository credentials (if configured)
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=repository
```

**Default ArgoCD Credentials:** `admin` / `admin` (configured in `values.yaml`)

#### Step 7: Deploy Infrastructure Stack

Deploys MetalLB, cert-manager, Traefik, Ceph CSI, and applies all IngressRoutes automatically.

```bash
cd "$(git rev-parse --show-toplevel)/apps"
./deploy-ingress-stack.sh
```

#### Step 8: Configure DNS

```bash
# Get Traefik LoadBalancer IP
kubectl get svc traefik -n traefik
```

Create A records for `traefik`, `argocd`, `harbor`, `openvas`, `faraday`, and `threatdragon` subdomains pointing to the Traefik external IP.

#### Step 9: Create Basic Auth Secret

```bash
htpasswd -nb admin YOUR_SECURE_PASSWORD
kubectl create secret generic basic-auth-secret --from-literal=users='admin:<hash>' -n traefik
```

#### Step 10: Enable ArgoCD Self-Management

```bash
kubectl apply -f apps/argocd/application.yaml
```

#### Step 11: Deploy Security Tools

```bash
cd "$(git rev-parse --show-toplevel)"

# Vulnerability scanning
kubectl apply -f apps/openvas/application.yaml

# Vulnerability management
kubectl apply -f apps/faraday/application.yaml

# Penetration testing
kubectl apply -f apps/metasploit/application.yaml

# Threat modeling
kubectl apply -f apps/threat-dragon/application.yaml

# Container registry
kubectl apply -f apps/harbor/application.yaml

# Verify all applications are syncing
kubectl get applications -n argocd
```

**Note:** OpenVAS feed synchronization takes 30-60 minutes on first deployment.

#### Step 12: Deploy Build VM and LOKI-RS Image

```bash
cd build-vm
./deploy-lxc.sh
```

After the build VM is deployed and Harbor is healthy:

```bash
ssh deploy@10.83.3.191
cd /opt/talos-cleanroom/apps/loki
HARBOR_PASSWORD="<your-harbor-password>" bash build-and-push.sh
```

#### Step 13: Verify Full Deployment

```bash
kubectl get pods -A
kubectl get applications -n argocd
kubectl get ingressroute -A
```

## Accessing Services

| Service | URL | Default Credentials |
|---------|-----|---------------------|
| Deployment WebUI | http://10.83.3.190:8000 | admin / admin |
| ArgoCD | https://argocd.knowledgeondemand.net | admin / admin |
| Traefik Dashboard | https://traefik.knowledgeondemand.net | admin / (basic auth secret) |
| Harbor | https://harbor.knowledgeondemand.net | admin / Harbor12345 (change on first login) |
| OpenVAS | https://openvas.knowledgeondemand.net | admin / admin |
| Faraday | https://faraday.knowledgeondemand.net | admin / (set via k8s secret) |
| Threat Dragon | https://threatdragon.knowledgeondemand.net | N/A (local storage) |
| Metasploit | `kubectl exec -it -n metasploit deploy/metasploit -c metasploit -- ./msfconsole` | N/A (CLI) |

> **Warning**: Change default passwords in production! Update ArgoCD password in `apps/argocd/values.yaml` and regenerate the bcrypt hash.

## Troubleshooting

See [DNS-MAPPING.md](docs/DNS-MAPPING.md) for complete DNS to IP address mappings.

### Common Issues

- **DNS Resolution**: Verify all FQDNs resolve correctly with `nslookup`
- **Network Access**: Ensure workstation can reach all hosts
- **Credentials**: Update `credentials.auto.tfvars` with correct Proxmox API token
- **Storage**: Verify Ceph pool `kubernetes` exists and monitors are reachable from worker nodes
- **OpenVAS feeds**: First sync takes 30-60 minutes; pods may restart during this time
- **Harbor 404**: The IngressRoute must point to the `harbor` service (nginx proxy), not `harbor-core`
- **LOKI pod Forbidden**: The `loki-scanner` namespace requires a privileged PodSecurity label: `kubectl label namespace loki-scanner pod-security.kubernetes.io/enforce=privileged`
- **Shell scripts Permission denied**: Scripts may lack the executable bit on Linux; run with `bash ./script.sh` or `chmod +x *.sh`
- **OpenVAS OOMKill**: ospd-openvas needs at least 4Gi memory limit; 1Gi causes OOM at ~96% scan progress

## References

- [Talos Linux Documentation](https://www.talos.dev/)
- [Proxmox Terraform Provider](https://registry.terraform.io/providers/bpg/proxmox/latest/docs)
- [talhelper Documentation](https://github.com/budimanjojo/talhelper)
- [SOPS Documentation](https://github.com/getsops/sops)
- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [Harbor Documentation](https://goharbor.io/docs/)
- [OpenVAS / Greenbone](https://greenbone.github.io/docs/)
- [Faraday Documentation](https://docs.faradaysec.com/)
- [LOKI-RS IOC Scanner](https://github.com/Neo23x0/Loki-RS)
- [SecureCodeBox](https://www.securecodebox.io/)
