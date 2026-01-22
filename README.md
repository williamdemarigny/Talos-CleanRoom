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
- **GitOps Ready**: ArgoCD-based application deployment with ingress stack included

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
│ OPNSENSE FW     │                              │     TALOS KUBERNETES      │                     │      METALLB IP POOL              │
├─────────────────┤                              │         CLUSTER           │                     │    10.83.3.200 - 10.83.3.250      │
│ opnsense-fw-01  │                              ├───────────────────────────┤                     └───────────────────────────────────┘
│ VMID: 1010      │                              │                           │
│ IP: 10.83.3.5   │                              │  ┌─────────────────────┐  │
├─────────────────┤                              │  │   CONTROL PLANE     │  │
│ opnsense-fw-02  │                              │  │   master-01         │  │
│ VMID: 1011      │                              │  │   VMID: 2000        │  │
│ IP: 10.83.3.6   │                              │  │   IP: 10.83.3.10    │  │
└─────────────────┘                              │  │   4 CPU / 8GB RAM   │  │
                                                 │  └─────────────────────┘  │
                                                 │                           │
                                                 │  ┌─────────────────────┐  │
                                                 │  │    WORKER NODES     │  │
                                                 │  ├─────────────────────┤  │
                                                 │  │ worker-01           │  │
                                                 │  │ VMID: 3001          │  │
                                                 │  │ IP: 10.83.3.15      │  │
                                                 │  │ 4 CPU / 8GB / +30G  │  │
                                                 │  ├─────────────────────┤  │
                                                 │  │ worker-02           │  │
                                                 │  │ VMID: 3002          │  │
                                                 │  │ IP: 10.83.3.16      │  │
                                                 │  │ 4 CPU / 8GB / +30G  │  │
                                                 │  ├─────────────────────┤  │
                                                 │  │ worker-03           │  │
                                                 │  │ VMID: 3003          │  │
                                                 │  │ IP: 10.83.3.17      │  │
                                                 │  │ 4 CPU / 8GB / +30G  │  │
                                                 │  └─────────────────────┘  │
                                                 └───────────────────────────┘

                             ┌──────────────────────────────────────────────────────────┐
                             │                 KUBERNETES NETWORK                       │
                             │  Pod Network:     10.14.0.0/16                           │
                             │  Service Network: 10.15.0.0/16                           │
                             └──────────────────────────────────────────────────────────┘

                             ┌──────────────────────────────────────────────────────────┐
                             │                 DEPLOYED SERVICES                        │
                             ├──────────────────────────────────────────────────────────┤
                             │  ArgoCD       → https://argocd.knowledgeondemand.net     │
                             │  Traefik      → https://traefik.knowledgeondemand.net    │
                             │  Longhorn     → https://longhorn.knowledgeondemand.net   │
                             │  MetalLB      → Load Balancer (L2 Mode)                  │
                             │  cert-manager → TLS Certificate Management               │
                             └──────────────────────────────────────────────────────────┘
```

## Project Structure

```
Talos-CleanRoom/
├── README.md                           # This file
├── LICENSE                             # Project license
├── TODO-traefik-deployment.md          # Traefik deployment checklist
│
└── Resources/
    ├── IAC/                            # IP-based deployment
    │   ├── README.md
    │   ├── .sops.yaml                  # SOPS encryption config
    │   ├── tfvars-to-talos-env.sh      # Terraform to Talos env converter
    │   ├── Terraform/
    │   │   └── Talos-Cluster-Create/
    │   │       ├── main.tf
    │   │       ├── variables.tf
    │   │       ├── locals.tf
    │   │       ├── cluster.auto.tfvars
    │   │       └── opnsense-configs/
    │   └── talos/
    │       ├── talconfig.yaml
    │       ├── talsecret.sops.yaml
    │       ├── talenv.yaml
    │       ├── apply-configs.sh
    │       └── clusterconfig/
    │
    └── IAC-DNS/                        # DNS/FQDN-based deployment (recommended)
        ├── README.md
        ├── DNS-MAPPING.md              # DNS to IP reference
        ├── .sops.yaml
        ├── tfvars-to-talos-env.sh
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
        │   ├── talconfig.yaml
        │   ├── talsecret.sops.yaml
        │   ├── talenv.yaml
        │   ├── apply-configs.sh
        │   └── clusterconfig/          # Generated machine configs
        │
        └── infrastructure/
            ├── argocd/                 # ArgoCD GitOps
            │   ├── namespace.yaml
            │   ├── values.yaml
            │   ├── application.yaml
            │   ├── install.sh
            │   └── uninstall.sh
            │
            └── projects/               # ArgoCD Applications
                ├── deploy-ingress-stack.sh
                ├── argocd/
                │   └── application.yaml
                ├── metallb/
                │   ├── application.yaml
                │   └── ip-pool.yaml
                ├── cert-manager/
                │   ├── application.yaml
                │   └── cluster-issuers.yaml
                ├── longhorn/
                │   ├── application.yaml
                │   ├── namespace.yaml
                │   └── values.yaml
                ├── kubescape/
                │   ├── application.yaml
                │   ├── namespace.yaml
                │   └── values.yaml
                └── traefik/
                    ├── application.yaml
                    ├── dashboard-ingressroute.yaml
                    ├── middlewares.yaml
                    ├── README.md
                    └── ingressroutes/
                        ├── argocd-ingressroute.yaml
                        └── longhorn-ingressroute.yaml
```

## Prerequisites

### Required Tools
| Tool | Version | Purpose |
|------|---------|---------|
| Terraform | >= 1.0 | Infrastructure provisioning |
| talhelper | v3.0.45+ | Talos configuration generator |
| talosctl | v1.11.6+ | Talos CLI tool |
| SOPS | v3.11.0+ | Secrets encryption (with Age) |
| jq | v1.8.1+ | JSON processor for scripts |
| curl | - | HTTP requests |

### Infrastructure Requirements
- **Proxmox VE** cluster with API access and valid API token
- **Talos ISO** uploaded to Proxmox storage (`nocloud-amd64.iso`)
- **OPNSense Template VM** (optional, for firewall deployment)

### Network Prerequisites
- **Network**: 10.83.3.0/24 (VLAN 3)
- **Gateway**: 10.83.3.1
- **DNS Server**: Configured with all required A records
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

## Deployment Workflow

### Step 1: Deploy Infrastructure with Terraform

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/terraform/talos-cluster-create"
terraform init
terraform plan -out=".tfplan"
terraform apply ".tfplan"
```

### Step 2: Generate Talos Configuration

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS"
./tfvars-to-talos-env.sh

cd talos
export SOPS_AGE_KEY_FILE=$HOME/.config/sops/age/keys.txt
talhelper gensecret > talsecret.sops.yaml
sops -e -i talsecret.sops.yaml
talhelper genconfig --env-file talenv.yaml
```

### Step 3: Apply Talos Configs and Bootstrap

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/talos"

# Apply configs and bootstrap (waits 180s then bootstraps automatically)
./apply-configs.sh --bootstrap

# Set talosconfig path
export TALOSCONFIG=$(pwd)/clusterconfig/talosconfig

# Wait for cluster health
talosctl health --nodes=talos-CleanRoom-master-01

# Get kubeconfig
talosctl kubeconfig --nodes=talos-CleanRoom-master-01 ~/.kube/config
```

**Alternative: Manual Bootstrap**
```bash
./apply-configs.sh                                      # Apply configs only
sleep 120                                               # Wait for VMs to reboot
talosctl bootstrap --nodes=talos-CleanRoom-master-01    # Bootstrap (run ONCE)
```

### Step 4: Verify Cluster

```bash
kubectl get nodes
kubectl get pods -A
```

### Step 5: Install ArgoCD

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/infrastructure/argocd"
chmod +x install.sh && ./install.sh

# Get admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo

# Verify ArgoCD is running (should have 2 replicas for HA components)
kubectl get pods -n argocd
kubectl get deployment -n argocd
```

### Step 6: Deploy Ingress Stack

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/infrastructure/projects"
chmod +x deploy-ingress-stack.sh && ./deploy-ingress-stack.sh
```

### Step 7: Configure Load Balancer IP

```bash
# Get Traefik LoadBalancer IP and update external DNS as needed
kubectl get svc traefik -n traefik
```

### Step 8: Create Basic Auth Secret

```bash
# Generate password hash (install apache2-utils if needed)
htpasswd -nb admin YOUR_SECURE_PASSWORD

# Create the secret (replace hash with output from above)
kubectl create secret generic basic-auth-secret \
  --from-literal=users='admin:$apr1$...' -n traefik
```

### Step 9: Apply IngressRoutes

```bash
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/infrastructure/projects"

# Traefik dashboard
kubectl apply -f traefik/dashboard-ingressroute.yaml

# ArgoCD and Longhorn
kubectl apply -f traefik/ingressroutes/
```

### Step 10: Verify Deployment

```bash
# Check all pods
kubectl get pods -n metallb-system
kubectl get pods -n cert-manager
kubectl get pods -n traefik
kubectl get pods -n argocd

# Verify HA distribution
kubectl get pods -n traefik -o wide
kubectl get pods -n argocd -o wide

# Check certificates and ingress routes
kubectl get certificates -A
kubectl get ingressroute -A
```

### Step 11: Enable ArgoCD Self-Management

```bash
cd "$(git rev-parse --show-toplevel)"
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/argocd/application.yaml

# Verify ArgoCD is managing itself
kubectl get applications -n argocd | grep argocd
```

## Accessing Services

| Service | URL | Credentials |
|---------|-----|-------------|
| Traefik Dashboard | https://traefik.knowledgeondemand.net | admin / (basic auth) |
| ArgoCD | https://argocd.knowledgeondemand.net | admin / (see below) |
| Longhorn | https://longhorn.knowledgeondemand.net | admin / (basic auth) |

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

See [DNS-MAPPING.md](Resources/IAC-DNS/DNS-MAPPING.md) for complete DNS to IP address mappings.

### Common Issues

- **DNS Resolution**: Verify all FQDNs resolve correctly with `nslookup`
- **Network Access**: Ensure workstation can reach all hosts
- **Credentials**: Update `credentials.auto.tfvars` with correct Proxmox API URL

## References

- [Talos Linux Documentation](https://www.talos.dev/)
- [Proxmox Terraform Provider](https://registry.terraform.io/providers/bpg/proxmox/latest/docs)
- [talhelper Documentation](https://github.com/budimanjojo/talhelper)
- [SOPS Documentation](https://github.com/getsops/sops)
