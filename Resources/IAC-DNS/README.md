# Talos Kubernetes Cluster on Proxmox - DNS-Based Infrastructure as Code

This directory contains a DNS-based version of the Infrastructure as Code (IaC) for deploying a Talos Linux Kubernetes cluster on Proxmox, with OPNsense firewall VMs. This version uses Fully Qualified Domain Names (FQDNs) instead of IP addresses, enabling deployment from a jumpbox within the network.

## Key Differences from IP-Based Configuration

### Architecture
- **IP-Based (Resources/IAC)**: Hardcoded IP addresses, designed for workstation deployment
- **DNS-Based (Resources/IAC-DNS)**: FQDN-based addressing, designed for jumpbox deployment within the network

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
talos-CleanRoom-worker-02.knowledgeondemand.net → 10.83.3.15
talos-CleanRoom-worker-03.knowledgeondemand.net → 10.83.3.16
talos-CleanRoom-worker-04.knowledgeondemand.net → 10.83.3.17
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
| talos-CleanRoom-master-01 | 2000 | Control Plane | talos-CleanRoom-master-01.knowledgeondemand.net | BC:24:21:A4:B2:97 | 2 | 8GB | 30G | - |
| talos-CleanRoom-worker-01 | 3001 | Worker | talos-CleanRoom-worker-02.knowledgeondemand.net | BC:24:21:4C:99:A1 | 2 | 8GB | 30G | 30G |
| talos-CleanRoom-worker-02 | 3002 | Worker | talos-CleanRoom-worker-03.knowledgeondemand.net | BC:24:21:4C:99:A2 | 2 | 8GB | 30G | 30G |
| talos-CleanRoom-worker-03 | 3003 | Worker | talos-CleanRoom-worker-04.knowledgeondemand.net | BC:24:21:4C:99:A3 | 2 | 8GB | 30G | 30G |

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
cd Resources/IAC-DNS/terraform/talos-cluster-create

terraform plan
terraform apply
```

### 2. Generate Talos Configuration

```bash
cd Resources/IAC-DNS
./tfvars-to-talos-env.sh

cd talos
talhelper genconfig --env-file talenv.yaml
```

### 3. Apply Talos Configs

```bash
cd Resources/IAC-DNS/talos
./apply-configs.sh --bootstrap
```

### 4. Verify Deployment

```bash
talosctl health
kubectl get nodes
kubectl get pods -A
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
