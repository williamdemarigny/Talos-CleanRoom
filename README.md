# Talos CleanRoom - Proxmox Kubernetes Cluster

A complete Terraform-based Infrastructure-as-Code (IaC) solution for provisioning and managing a Talos Kubernetes cluster on Proxmox.

## Overview

This project provides automated deployment and lifecycle management of a Talos Kubernetes cluster across a Proxmox cluster. It includes:

- **Cluster Provisioning**: Deploy Talos VMs across your Proxmox cluster with automatic node distribution
- **Automatic Node Discovery**: Discovers available Proxmox nodes and distributes VMs using round-robin scheduling
- **Cleanup Operations**: Power down and delete VMs with automatic shutdown
- **Flexible Configuration**: Support for control plane, worker nodes, and GPU workers

## Project Structure

```
Talos-CleanRoom/
├── Resources/
│   └── IAC/
│       └── Terraform/
│           └── Talos-Cluster/                  # Unified provisioning & cleanup module
│               ├── variables.tf                # All variables (provisioning + cleanup)
│               ├── main.tf                     # Provisioning resources
│               ├── cleanup.tf                  # Cleanup resources (optional)
│               ├── locals.tf                   # Local values
│               ├── cluster.auto.tfvars         # Provisioning configuration
│               ├── cleanup.auto.tfvars         # Cleanup configuration (optional)
│               ├── credentials.auto.tfvars     # Proxmox credentials (gitignored)
│               └── .gitignore
│
└── README.md
```

## Prerequisites

- **Terraform** >= 1.0
- **Proxmox VE** cluster with API access
- **Talos ISOs** uploaded to Proxmox storage
- Valid Proxmox API token with VM management permissions

## Quick Start

### 1. Configure Your Environment

Edit `Resources/IAC/Terraform/Talos-Cluster/credentials.auto.tfvars`:

```hcl
proxmox_api_url      = "https://your-proxmox:8006/api2/json"
proxmox_node         = "pve01"
proxmox_api_token    = "terraform@pve!provider=..."
proxmox_pool         = "talos-cluster"
proxmox_ssh_password = "..."
```

Edit `Resources/IAC/Terraform/Talos-Cluster/cluster.auto.tfvars`:

```hcl
talos_iso_file = "cephfs:iso/talos-1.12.1.iso"
disk_storage = "CleanRoom_Storage"
network_bridge = "vmbr0"
vlan_id = 3

nodes = [
  {
    name = "talos-master-01"
    vmid = 2000
    role = "controlplane"
    ip = "10.83.3.10"
    # ... other fields
  },
  # ... additional nodes
]
```

### 2. Provision the Cluster

```bash
cd Resources/IAC/Terraform/Talos-Cluster

# Initialize Terraform
terraform init

# Review the deployment plan
terraform plan

# Deploy the cluster
terraform apply
```

### 3. Cleanup (Optional)

To power down and delete VMs:

```bash
# Edit cleanup.auto.tfvars
vi cleanup.auto.tfvars

# Set cleanup_enabled = true
# Set vm_ids_to_cleanup = [2000, 3001, 3002, 3003]

# Review cleanup plan
terraform plan

# Execute cleanup
terraform apply
```

## Configuration

### Main Cluster Configuration

Edit `cluster.auto.tfvars`:

```hcl
# Talos ISO configuration
talos_iso_file = "cephfs:iso/talos-1.12.1.iso"

# Storage configuration
disk_storage = "CleanRoom_Storage"
additional_disk_storage = "CleanRoom_Storage"

# Network configuration
network_bridge = "vmbr0"
vlan_id = 3

# Node definitions
nodes = [
  {
    name = "talos-CleanRoom-master-01"
    vmid = 2000
    role = "controlplane"
    ip = "10.83.3.10"
    cores = 2
    memory = 8192
    disk_size = "30G"
    tags = ["talos", "controlplane"]
  },
  # ... additional nodes
]
```

### Cleanup Configuration

Edit `cleanup.auto.tfvars`:

```hcl
# Enable cleanup mode (DANGEROUS - will delete VMs)
cleanup_enabled = true

# VM IDs to delete
vm_ids_to_cleanup = [2000, 3001, 3002, 3003]

# Shutdown timeout in seconds
shutdown_timeout = 300
```

## Features

### Automatic Cluster Node Discovery

Automatically discovers available Proxmox nodes and distributes VMs using round-robin scheduling.

### Node Affinity (Manual Pinning)

Pin specific VMs to specific Proxmox nodes:

```hcl
node_affinity = {
  "talos-CleanRoom-master-01" = "pve01"
  "talos-CleanRoom-worker-01" = "pve02"
}
```

### VLAN Support

Configure VLAN tagging for all VMs:

```hcl
vlan_id = 3
```

### Resource Pooling

VMs organized in Proxmox resource pools:

```hcl
proxmox_pool = "talos-cluster"
```

### GPU Worker Support

```hcl
talos_gpu_iso_file = "cephfs:iso/talos-1.12.1-gpu.iso"

nodes = [
  {
    name = "talos-CleanRoom-gpu-worker-01"
    role = "worker-gpu"
    # ... other config
  }
]
```

### Additional Storage Disks

```hcl
nodes = [
  {
    # ... other config
    additional_disk_size = "30G"
  }
]
```

## Outputs

View outputs after deployment:

```bash
terraform output
```

Shows:
- VM MAC addresses
- VM details (VMID, IP, role, specs)
- Node roles and distribution
- Cluster status

## Best Practices

1. Always run `terraform plan` before `terraform apply`
2. Keep `credentials.auto.tfvars` secure and gitignored
3. Use resource pools for VM organization
4. Test cleanup in non-production environment first
5. Document all configuration changes

## Security Considerations

- ✅ API tokens marked as sensitive
- ✅ Credentials in separate file (gitignored)
- ⚠️ Store credentials in secret management for CI/CD

## Support

For issues or questions, refer to troubleshooting section in extended documentation.

---

**Last Updated**: 2024
**Terraform Version**: >= 1.0
**Proxmox Provider Version**: 0.82.1

