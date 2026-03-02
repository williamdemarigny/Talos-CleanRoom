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
├── DeployCluster.sh                    # CLI deployment orchestrator
├── deployment_tui.py                   # Terminal UI for deployment
│
├── deployment-webui/                   # Web UI for deployment + security scanning
│   ├── README.md                       # Web UI deployment guide
│   ├── README-TECHNICAL.md             # Technical architecture docs
│   ├── deploy-lxc.sh                   # Automated LXC deployment
│   ├── app/                            # FastAPI application
│   ├── templates/                      # Jinja2 HTML templates
│   ├── static/                         # CSS, JS assets
│   ├── scripts/                        # Container setup scripts
│   └── terraform/                      # LXC container Terraform config
│
├── build-vm/                           # Docker image build VM (LXC)
│   ├── README.md                       # Build VM deployment guide
│   ├── deploy-lxc.sh                   # Automated LXC deployment
│   ├── scripts/                        # Container setup (Docker CE, kubectl)
│   └── terraform/                      # LXC container Terraform config
│
├── ceph-storage/                       # Ceph CSI RBD storage integration
│   ├── application.yaml                # ArgoCD Application for ceph-csi-rbd
│   ├── ceph-csi-secret.sops.yaml       # Encrypted Ceph credentials
│   └── storageclass.yaml               # ceph-rbd StorageClass (default)
│
└── Resources/
    └── IAC-DNS/                        # DNS/FQDN-based deployment
        ├── DNS-MAPPING.md              # DNS to IP reference
        ├── .sops.yaml                  # SOPS encryption config
        ├── tfvars-to-talos-env.sh      # Terraform to Talos env conversion
        │
        ├── terraform/
        │   └── talos-cluster-create/
        │       ├── main.tf
        │       ├── variables.tf
        │       ├── locals.tf
        │       ├── cluster.auto.tfvars
        │       └── credentials.auto.tfvars   # (gitignored)
        │
        ├── talos/
        │   ├── talconfig.yaml          # Talos cluster definition
        │   ├── talsecret.sops.yaml     # Encrypted secrets
        │   ├── talenv.yaml             # Environment variables
        │   ├── apply-configs.sh        # Config application + bootstrap
        │   └── clusterconfig/          # Generated machine configs
        │
        └── infrastructure/
            ├── argocd/                 # ArgoCD installation + credentials
            │   ├── install.sh / uninstall.sh
            │   ├── values.yaml
            │   └── repo-credentials.sops.yaml
            │
            └── projects/               # ArgoCD Applications
                ├── deploy-ingress-stack.sh
                ├── argocd/             # ArgoCD self-management
                ├── metallb/            # L2 load balancer
                ├── cert-manager/       # TLS certificates
                ├── traefik/            # Ingress controller
                ├── metrics-server/     # Kubernetes metrics
                ├── harbor/             # Private container registry
                ├── openvas/            # Vulnerability scanner
                ├── faraday/            # Vulnerability management
                ├── metasploit/         # Penetration testing
                ├── securecodebox/      # Automated security scanning (Nmap, Nikto, etc.)
                ├── threat-dragon/      # Threat modeling
                ├── loki/               # LOKI-RS IOC scanner image
                └── network-policies/   # Zero-trust namespace isolation
```

## Prerequisites

### Required Tools
| Tool | Version | Purpose |
|------|---------|---------|
| Terraform | >= 1.0 | Infrastructure provisioning |
| talhelper | v3.0.45+ | Talos configuration generator |
| talosctl | v1.12.2+ | Talos CLI tool |
| SOPS | v3.8.1+ | Secrets encryption (with Age) |
| jq | v1.8.1+ | JSON processor for scripts |
| curl | - | HTTP requests |
| helm | v3.0+ | Kubernetes package manager |
| kubectl | v1.29+ | Kubernetes CLI |

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

Deploy the WebUI LXC container and use the browser-based interface:

```bash
cd deployment-webui
./deploy-lxc.sh
```

Access the UI at `http://10.83.3.190:8000` and use the dashboard to provision the cluster. See [deployment-webui/README.md](deployment-webui/README.md) for details.

### Option B: CLI Deployment

#### Step 1: Deploy Infrastructure with Terraform

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/terraform/talos-cluster-create"
terraform init
terraform plan -out=".tfplan"
terraform apply ".tfplan"
```

#### Step 2: Generate Talos Configuration

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS"
./tfvars-to-talos-env.sh

cd talos
export SOPS_AGE_KEY_FILE=$HOME/.config/sops/age/keys.txt
talhelper gensecret > talsecret.sops.yaml
sops -e -i talsecret.sops.yaml
talhelper genconfig --env-file talenv.yaml
```

#### Step 3: Apply Talos Configs and Bootstrap
```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/talos"
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
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/infrastructure/argocd"
# Edit repo-credentials.yaml - paste private key from: cat ~/.ssh/argocd_deploy_key

# Encrypt with SOPS
sops --config ../../talos/.sops.yaml --encrypt repo-credentials.yaml > repo-credentials.sops.yaml
rm repo-credentials.yaml  # Delete unencrypted file
```

#### Step 6: Install ArgoCD

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/infrastructure/argocd"
chmod +x install.sh && ./install.sh

# Verify ArgoCD is running
kubectl get pods -n argocd
kubectl get deployment -n argocd

# Verify repository credentials (if configured)
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=repository
```

**Default ArgoCD Credentials:** `admin` / `admin` (configured in `values.yaml`)

#### Step 7: Deploy Infrastructure Stack

Deploys MetalLB, cert-manager, Traefik, Ceph CSI, and applies all IngressRoutes automatically.

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/infrastructure/projects"
chmod +x deploy-ingress-stack.sh && ./deploy-ingress-stack.sh
```

#### Step 8: Configure Load Balancer IP

```bash
# Get Traefik LoadBalancer IP and create DNS A records for *.knowledgeondemand.net
kubectl get svc traefik -n traefik
```

Create A records for `traefik`, `argocd`, `harbor`, `openvas`, `faraday`, and `threatdragon` subdomains pointing to the Traefik external IP.

#### Step 9: Create Basic Auth Secret

```bash
# Generate password hash (install apache2-utils if needed)
htpasswd -nb admin YOUR_SECURE_PASSWORD

# Create the secret
kubectl create secret generic basic-auth-secret --from-literal=users='admin:<hash>' -n traefik
```

#### Step 10: Verify Deployment

```bash
# Check all infrastructure pods
kubectl get pods -n metallb-system
kubectl get pods -n cert-manager
kubectl get pods -n traefik
kubectl get pods -n argocd

# Check certificates and ingress routes
kubectl get certificates -A
kubectl get ingressroute -A
```

#### Step 11: Enable ArgoCD Self-Management

```bash
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/argocd/application.yaml

# Verify ArgoCD is managing itself
kubectl get applications -n argocd | grep argocd
```

Once enabled, ArgoCD will auto-sync all applications when you push changes to the repository.

#### Step 12: Deploy Security Tools (Manual)

If not using ArgoCD auto-sync, manually deploy the security applications:

```bash
cd "$(git rev-parse --show-toplevel)"

# Vulnerability scanning
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/openvas/application.yaml

# Vulnerability management
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/faraday/application.yaml

# Penetration testing
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/metasploit/application.yaml

# Threat modeling
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/threat-dragon/application.yaml

# Container registry with Trivy scanning
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/harbor/application.yaml

# Automated security scanning (SecureCodeBox)
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/securecodebox/operator-application.yaml
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/securecodebox/nmap-application.yaml

# Zero-trust namespace isolation
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/network-policies/application.yaml

# Verify all applications are syncing
kubectl get applications -n argocd
```

**Note:** OpenVAS feed synchronization takes 30-60 minutes on first deployment.

#### Step 13: Deploy Build VM (Optional)

Deploy the build VM LXC container for building and pushing Docker images to Harbor:

```bash
cd build-vm
./deploy-lxc.sh
```

Then build and push the LOKI-RS scanner image:

```bash
ssh deploy@10.83.3.191
cd /opt/talos-cleanroom/Resources/IAC-DNS/infrastructure/projects/loki
./build-and-push.sh
```

## Accessing Services

| Service | URL | Default Credentials |
|---------|-----|---------------------|
| Deployment WebUI | http://10.83.3.190:8000 | admin / admin |
| ArgoCD | https://argocd.knowledgeondemand.net | admin / admin |
| Traefik Dashboard | https://traefik.knowledgeondemand.net | admin / (basic auth secret) |
| Harbor | https://harbor.knowledgeondemand.net | admin / (set at deploy) |
| OpenVAS | https://openvas.knowledgeondemand.net | admin / admin |
| Faraday | https://faraday.knowledgeondemand.net | admin / (set via k8s secret) |
| Threat Dragon | https://threatdragon.knowledgeondemand.net | N/A (local storage) |
| Metasploit | `kubectl exec -it -n metasploit deploy/metasploit -c metasploit -- ./msfconsole` | N/A (CLI) |

> **Warning**: Change default passwords in production! Update ArgoCD password in `infrastructure/argocd/values.yaml` and regenerate the bcrypt hash.

## Troubleshooting

See [DNS-MAPPING.md](Resources/IAC-DNS/DNS-MAPPING.md) for complete DNS to IP address mappings.

### Common Issues

- **DNS Resolution**: Verify all FQDNs resolve correctly with `nslookup`
- **Network Access**: Ensure workstation can reach all hosts
- **Credentials**: Update `credentials.auto.tfvars` with correct Proxmox API token
- **Storage**: Verify Ceph pool `kubernetes` exists and monitors are reachable from worker nodes
- **OpenVAS feeds**: First sync takes 30-60 minutes; pods may restart during this time

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
