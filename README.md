# Talos CleanRoom - Proxmox Kubernetes Cluster

A complete Terraform-based Infrastructure-as-Code (IaC) solution for provisioning and managing a Talos Kubernetes cluster on Proxmox.

## Overview

This project provides automated deployment and lifecycle management of a Talos Kubernetes cluster across a Proxmox cluster, with optional OPNSense firewall deployment. It supports two deployment strategies: IP-based and DNS/FQDN-based configurations.

**Key Features:**

- **Dual Deployment Strategies**: IP-based (`IAC/`) or DNS/FQDN-based (`IAC-DNS/`) infrastructure configuration
- **OPNSense Firewall Deployment**: Optional deployment of OPNSense firewall appliances (deployed first)
- **Cluster Provisioning**: Deploy Talos VMs across your Proxmox cluster with automatic node distribution
- **Automatic Node Discovery**: Discovers available Proxmox nodes and distributes VMs using round-robin scheduling
- **Talos Configuration Management**: Automated config generation with talhelper and SOPS-encrypted secrets
- **Bootstrap Automation**: Scripts to discover VM IPs and apply Talos configurations automatically
- **Flexible Configuration**: Support for control plane and worker nodes
- **Ordered Deployment**: OPNSense firewalls deploy first, followed by Talos cluster nodes

## Project Structure

```
Talos-CleanRoom/
├── Resources/
│   ├── IAC/                                    # IP-based deployment (primary)
│   │   ├── README.md                           # IAC-specific documentation
│   │   ├── tfvars-to-talos-env.sh             # Generate talenv.yaml from Terraform vars
│   │   ├── Terraform/
│   │   │   └── Talos-Cluster-Create/          # Terraform configuration
│   │   │       ├── main.tf                    # VM provisioning resources
│   │   │       ├── variables.tf               # Variable declarations
│   │   │       ├── locals.tf                  # Local value definitions
│   │   │       ├── cluster.auto.tfvars        # Cluster configuration
│   │   │       ├── credentials.auto.tfvars    # Proxmox credentials (gitignored)
│   │   │       └── opnsense-configs/          # OPNSense configuration & guides
│   │   │           ├── README.md
│   │   │           └── QUICK-START.md
│   │   └── talos/                             # Talos configuration
│   │       ├── talconfig.yaml                 # Talos cluster blueprint
│   │       ├── talsecret.sops.yaml            # SOPS-encrypted secrets
│   │       ├── talenv.yaml                    # Generated environment variables
│   │       ├── apply-configs.sh               # Auto-apply configs to VMs
│   │       └── clusterconfig/                 # Generated machine configs
│   │
│   └── IAC-DNS/                               # DNS/FQDN-based deployment (alternative)
│       ├── README.md                          # DNS deployment documentation
│       ├── DNS-MAPPING.md                     # DNS to IP reference table
│       ├── tfvars-to-talos-env.sh            # Generate talenv.yaml (FQDN version)
│       ├── terraform/
│       │   └── talos-cluster-create/         # Terraform configuration (FQDN)
│       ├── talos/                            # Talos configuration (FQDN)
│       │   ├── talconfig.yaml
│       │   ├── apply-configs.sh
│       │   └── clusterconfig/
│       └── infrastructure/                    # Kubernetes infrastructure components
│           └── argocd/                        # ArgoCD GitOps deployment
│               ├── namespace.yaml
│               ├── values.yaml
│               ├── install.sh
│               └── uninstall.sh
│
├── .gitignore                                 # Excludes credentials and state files
└── README.md                                  # This file
```

## Prerequisites

- **Terraform** >= 1.0
- **Proxmox VE** cluster with API access
- **Talos ISO** uploaded to Proxmox storage (e.g., `nocloud-amd64.iso`)
- **OPNSense Template VM** (optional, for firewall deployment)
- **talhelper** (v3.0.45+) - Talos configuration generator
- **talosctl** (v1.11.6+) - Talos CLI tool
- **SOPS** (v3.11.0+) with Age encryption for secrets management
- **jq** (v1.8.1+) - JSON processor for scripts
- Valid Proxmox API token with VM management permissions

### Network Configuration
- **Network**: 10.83.3.0/24
- **Gateway**: 10.83.3.1
- **VLAN**: 3
- **Addressing**: DNS resolution via FQDNs

## DNS Records Required

Before deploying, ensure the following DNS A records are configured:

### Proxmox Cluster Nodes
```
pve01.knowledgeondemand.net    → 10.83.2.20
pve02.knowledgeondemand.net    → 10.83.2.21
pve03.knowledgeondemand.net    → 10.83.2.22
pve04.knowledgeondemand.net    → 10.83.2.23
```

### OPNsense Firewall VMs
```
opnsense-fw-01.knowledgeondemand.net → 10.83.3.5
opnsense-fw-02.knowledgeondemand.net → 10.83.3.6
```

### Talos Kubernetes Cluster
```
talos-CleanRoom-master-01.knowledgeondemand.net → 10.83.3.10
talos-CleanRoom-worker-01.knowledgeondemand.net → 10.83.3.15
talos-CleanRoom-worker-02.knowledgeondemand.net → 10.83.3.16
talos-CleanRoom-worker-03.knowledgeondemand.net → 10.83.3.17
```

## Virtual Machines

### OPNsense Firewall VMs
| Name | VMID | FQDN | MAC | Cores | Memory | Disk |
|------|------|------|-----|-------|--------|------|
| opnsense-fw-01 | 1010 | opnsense-fw-01.knowledgeondemand.net | BC:24:21:F1:00:01 | 2 | 8GB | 30G |
| opnsense-fw-02 | 1011 | opnsense-fw-02.knowledgeondemand.net | BC:24:21:F1:00:02 | 2 | 8GB | 30G |

### Talos Kubernetes Cluster
| Name | VMID | Role | FQDN | MAC | Cores | Memory | Primary Disk | Additional Disk |
|------|------|------|------|-----|-------|--------|--------------|-----------------|
| talos-CleanRoom-master-01 | 2000 | Control Plane | talos-CleanRoom-master-01.knowledgeondemand.net | BC:24:21:A4:B2:97 | 4 | 8GB | 30G | - |
| talos-CleanRoom-worker-01 | 3001 | Worker | talos-CleanRoom-worker-01.knowledgeondemand.net | BC:24:21:4C:99:A1 | 4 | 8GB | 30G | 30G |
| talos-CleanRoom-worker-02 | 3002 | Worker | talos-CleanRoom-worker-02.knowledgeondemand.net | BC:24:21:4C:99:A2 | 4 | 8GB | 30G | 30G |
| talos-CleanRoom-worker-03 | 3003 | Worker | talos-CleanRoom-worker-03.knowledgeondemand.net | BC:24:21:4C:99:A3 | 4 | 8GB | 30G | 30G |

## Directory Structure

```
Resources/IAC-DNS/
├── terraform/
│   └── talos-cluster-create/
│       ├── main.tf                      # Main Terraform configuration (FQDN-based)
│       ├── variables.tf                 # Variable definitions (FQDN fields)
│       ├── locals.tf                    # Local values (FQDN references)
│       ├── cluster.auto.tfvars          # Cluster configuration (FQDNs)
│       └── credentials.auto.tfvars      # Proxmox credentials (FQDN API URL)
├── talos/
│   ├── talconfig.yaml                   # Talos cluster configuration (FQDN-based)
│   ├── talsecret.sops.yaml             # SOPS-encrypted secrets
│   ├── talenv.yaml                      # Generated environment variables (FQDNs)
│   ├── apply-configs.sh                 # Automation script for applying configs
│   └── clusterconfig/                   # Generated Talos machine configs
├── infrastructure/
│   └── argocd/
│       ├── namespace.yaml               # ArgoCD namespace definition
│       ├── values.yaml                  # Helm chart values
│       ├── install.sh                   # Installation script
│       └── uninstall.sh                 # Uninstallation script
├── tfvars-to-talos-env.sh              # Extract Terraform vars for Talos (FQDN support)
├── DNS-MAPPING.md                       # DNS to IP address mapping reference
└── README.md                            # This file
```

## Prerequisites

### Required Tools
- Terraform (v1.x+)
- talhelper (v3.0.45)
- talosctl (v1.11.6)
- sops (v3.11.0)
- jq (v1.8.1)
- curl

### Network Prerequisites
1. **DNS Server**: Configured with all required A records
2. **Network Access**: Jumpbox must be able to resolve and reach all FQDNs
3. **DHCP**: Configured for 10.83.3.0/24 network
4. **Firewall**: Network access from jumpbox to Proxmox cluster and VMs

## Deployment Workflow

### 1. Deploy Infrastructure with Terraform

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/terraform/talos-cluster-create"

terraform init
terraform plan -out=".tfplan"
terraform apply ".tfplan"
```

### 2. Generate Talos Configuration

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS"
./tfvars-to-talos-env.sh

cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/talos"
export SOPS_AGE_KEY_FILE=$HOME/.config/sops/age/keys.txt
talhelper gensecret > talsecret.sops.yaml
sops -e -i talsecret.sops.yaml
export SOPS_AGE_KEY_FILE=$HOME/.config/sops/age/keys.txt
talhelper genconfig --env-file talenv.yaml
```

### 3. Apply Talos Configs

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/talos"

# Apply configs and bootstrap the cluster (--bootstrap waits 180s then bootstraps automatically)
./apply-configs.sh --bootstrap

# Set talosconfig path
export TALOSCONFIG=$(pwd)/clusterconfig/talosconfig

# Wait for cluster to be healthy
talosctl health --nodes=talos-CleanRoom-master-01

# Get kubeconfig
talosctl kubeconfig --nodes=talos-CleanRoom-master-01 ~/.kube/config
```

**Alternative: Manual Bootstrap**

If you prefer to bootstrap manually, omit the `--bootstrap` flag:

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/talos"

# Apply configs only (no bootstrap)
./apply-configs.sh

# Set talosconfig path
export TALOSCONFIG=$(pwd)/clusterconfig/talosconfig

# Wait 1-2 minutes for VMs to reboot, then bootstrap (run ONCE on ONE control plane node)
talosctl bootstrap --nodes=talos-CleanRoom-master-01

# Wait for cluster to be healthy
talosctl health --nodes=talos-CleanRoom-master-01

# Get kubeconfig
talosctl kubeconfig --nodes=talos-CleanRoom-master-01 ~/.kube/config
```

### 4. Verify Deployment

```bash
kubectl get nodes
kubectl get pods -A
```

### 5. Install ArgoCD

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/infrastructure/argocd"
chmod +x install.sh
./install.sh
```

**Get the admin password:**
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
```

# Verify ArgoCD is running (should have 2 replicas for HA components)
```bash
kubectl get pods -n argocd
kubectl get deployment -n argocd
```

### 6: Deploy the Ingress Stack
```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/infrastructure/projects"
chmod +x deploy-ingress-stack.sh
./deploy-ingress-stack.sh
```

### 7: Get Traefik LoadBalancer IP
### Update External DNS as needed
```bash
kubectl get svc traefik -n traefik
```

### 8: Create Basic Auth Secret
```bash
# Generate password hash (install apache2-utils if needed)
htpasswd -nb admin YOUR_SECURE_PASSWORD
```
# Create the secret (replace the hash with output from above)
```bash
kubectl create secret generic basic-auth-secret --from-literal=users='admin:$apr1$...' -n traefik
```
###9: Apply IngressRoutes
```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/infrastructure/projects"
kubectl apply -f /c/Users/Administrator/Documents/GitHub/Talos-CleanRoom/Resources/IAC-DNS/infrastructure/projects/traefik/dashboard-ingressroute.yaml
kubectl apply -f /c/Users/Administrator/Documents/GitHub/Talos-CleanRoom/Resources/IAC-DNS/infrastructure/projects/traefik/ingressroutes/

# Traefik dashboard
kubectl apply -f traefik/dashboard-ingressroute.yaml

# ArgoCD and Longhorn
kubectl apply -f traefik/ingressroutes/
```

### 9: Verify Deployment
```bash
# Check all pods are running
kubectl get pods -n metallb-system
kubectl get pods -n cert-manager
kubectl get pods -n traefik
kubectl get pods -n argocd

# Verify HA - pods should be distributed across nodes
kubectl get pods -n traefik -o wide
kubectl get pods -n argocd -o wide

# Check certificates
kubectl get certificates -A

# Check IngressRoutes
kubectl get ingressroute -A
```
# Enable ArgoCD Self-Management
# Apply the self-managing Application
```bash
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/argocd/application.yaml

# Verify ArgoCD is now managing itself
kubectl get applications -n argocd | grep argocd
```

### 10: Access Services

| Service | URL | Credentials |
|---------|-----|-------------|
| Traefik Dashboard | https://traefik.knowledgeondemand.net | admin / (basic auth password) |
| ArgoCD | https://argocd.knowledgeondemand.net | admin / (see below) |
| Longhorn | https://longhorn.knowledgeondemand.net | admin / (basic auth password) |

**Get ArgoCD admin password:**
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
```

## Benefits of DNS-Based Deployment

1. **Portability**: Deploy from workstation or jumpbox without code changes
2. **Flexibility**: IP addresses can change without modifying infrastructure code
3. **Maintainability**: Centralized DNS management
4. **Scalability**: Easier to add/move nodes
5. **Network Integration**: Better integration with existing network infrastructure

## Troubleshooting

See [DNS-MAPPING.md](DNS-MAPPING.md) for complete DNS to IP address mappings.

### Common Issues

- **DNS Resolution**: Verify all FQDNs resolve correctly with `nslookup`
- **Network Access**: Ensure jumpbox can reach all hosts
- **Credentials**: Update `credentials.auto.tfvars` with correct Proxmox API URL

## References

- [Talos Linux Documentation](https://www.talos.dev/)
- [Proxmox Terraform Provider](https://registry.terraform.io/providers/bpg/proxmox/latest/docs)
- [talhelper Documentation](https://github.com/budimanjojo/talhelper)
- [SOPS Documentation](https://github.com/getsops/sops)
