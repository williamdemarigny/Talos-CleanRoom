# Talos CleanRoom - Proxmox Kubernetes Cluster

A complete Terraform-based Infrastructure-as-Code (IaC) solution for provisioning and managing a Talos Kubernetes cluster on Proxmox.

## Overview

This project provides automated deployment and lifecycle management of a Talos Kubernetes cluster across a Proxmox cluster. It includes:

- **Cluster Provisioning**: Deploy Talos VMs across your Proxmox cluster with automatic node distribution
- **Automatic Node Discovery**: Discovers available Proxmox nodes and distributes VMs using round-robin scheduling
- **Flexible Configuration**: Support for control plane, worker nodes, and GPU workers
- **Resource Outputs**: Comprehensive VM details, MAC addresses, and cluster status information

## Project Structure

```
Talos-CleanRoom/
├── Resources/
│   └── IAC/
│       └── Terraform/
│           └── Talos-Cluster-Create/           # Cluster provisioning module
│               ├── variables.tf                # Variable declarations
│               ├── main.tf                     # Provisioning resources
│               ├── locals.tf                   # Local value definitions
│               ├── cluster.auto.tfvars         # Cluster configuration
│               ├── credentials.auto.tfvars     # Proxmox credentials (gitignored)
│               ├── .terraform.lock.hcl         # Terraform lock file
│               └── terraform.tfstate           # Terraform state
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

Edit `Resources/IAC/Terraform/Talos-Cluster-Create/credentials.auto.tfvars`:

```hcl
proxmox_api_url      = "https://your-proxmox:8006/api2/json"
proxmox_node         = "pve01"
proxmox_api_token    = "terraform@pve!provider=..."
proxmox_pool         = "talos-cluster"
proxmox_ssh_password = "..."
```

Edit `Resources/IAC/Terraform/Talos-Cluster-Create/cluster.auto.tfvars`:

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
cd Resources/IAC/Terraform/Talos-Cluster-Create

# Initialize Terraform
terraform init

# Review the deployment plan
terraform plan

# Deploy the cluster
terraform apply
```

### 3. Destroy the Cluster (Optional)

To remove all VMs and clean up resources:

```bash
cd Resources/IAC/Terraform/Talos-Cluster-Create

# Review what will be destroyed
terraform plan -destroy

# Destroy all resources
terraform destroy
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

### Credentials Configuration

Create `credentials.auto.tfvars` (this file should be gitignored):

```hcl
# Proxmox API configuration
proxmox_api_url      = "https://your-proxmox-host:8006/api2/json"
proxmox_node         = "pve01"                    # Default node
proxmox_api_token    = "terraform@pve!provider=..."
proxmox_pool         = "talos-cluster"            # Optional resource pool
proxmox_ssh_password = "your-ssh-password"        # For VM operations
```

**Important**: Never commit `credentials.auto.tfvars` to version control!

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
- **vm_mac_addresses**: MAC addresses for all VMs
- **vm_details**: Complete VM information (VMID, name, IP, role, Proxmox node, specs)
- **node_roles**: Summary of nodes by role (controlplane, worker, worker-gpu)
- **cluster_status**: Overall cluster configuration and health
- **vm_distribution**: How VMs are distributed across Proxmox nodes

## Best Practices

1. **Always run `terraform plan` before `terraform apply`** to review changes
2. **Keep `credentials.auto.tfvars` secure and gitignored** - never commit credentials
3. **Use resource pools** for VM organization in Proxmox
4. **Test in non-production** before deploying to production clusters
5. **Document configuration changes** for team visibility
6. **Review node distribution** to ensure balanced VM placement across Proxmox nodes
7. **Use VLAN tagging** for network isolation when running multiple clusters

## Security Considerations

- ✅ **Sensitive variables**: API tokens and passwords marked as sensitive in Terraform
- ✅ **Separate credentials file**: Credentials isolated in `credentials.auto.tfvars`
- ✅ **Gitignore configured**: Credentials file pattern added to `.gitignore`
- ⚠️ **Secret management**: For CI/CD pipelines, use proper secret management (HashiCorp Vault, AWS Secrets Manager, etc.)
- ⚠️ **State file security**: Terraform state files contain sensitive data - store in secure backend (S3 with encryption, Terraform Cloud, etc.)
- ⚠️ **Network security**: Ensure Proxmox API is accessible only from trusted networks
- ⚠️ **API token permissions**: Use minimal required permissions for Terraform API tokens

## Troubleshooting

### Common Issues

**VM Creation Fails**
- Verify Proxmox API token has correct permissions
- Ensure ISO file exists at the specified storage location
- Check that target storage has sufficient space
- Verify VLAN ID exists on the network bridge

**Node Distribution Issues**
- Check that Proxmox cluster nodes are online and accessible
- Verify `proxmox_node` variable matches an available node
- Review `node_affinity` configuration for conflicts

**Network Configuration Problems**
- Ensure VLAN ID is valid (1-4094)
- Verify network bridge exists on all Proxmox nodes
- Check that IP addresses don't conflict with existing VMs

**State File Conflicts**
- Use remote state backend for team collaboration
- Run `terraform refresh` to sync state with actual infrastructure
- Consider `terraform import` for existing resources

## Additional Resources

- [Talos Linux Documentation](https://www.talos.dev/)
- [Proxmox VE API Documentation](https://pve.proxmox.com/pve-docs/api-viewer/)
- [Terraform Proxmox Provider](https://github.com/bpg/terraform-provider-proxmox)

---

**Last Updated**: January 2026
**Terraform Version**: >= 1.0
**Proxmox Provider Version**: 0.82.1
**Talos Version**: v1.12.1

