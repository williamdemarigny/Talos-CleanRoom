# Talos CleanRoom - Proxmox Kubernetes Cluster

A complete Terraform-based Infrastructure-as-Code (IaC) solution for provisioning and managing a Talos Kubernetes cluster on Proxmox.

## Overview

This project provides automated deployment and lifecycle management of a Talos Kubernetes cluster across a Proxmox cluster, with optional OPNSense firewall deployment. It includes:

- **OPNSense Firewall Deployment**: Optional deployment of OPNSense firewall appliances (deployed first)
- **Cluster Provisioning**: Deploy Talos VMs across your Proxmox cluster with automatic node distribution
- **Automatic Node Discovery**: Discovers available Proxmox nodes and distributes VMs using round-robin scheduling
- **Flexible Configuration**: Support for control plane, worker nodes, and GPU workers
- **Ordered Deployment**: OPNSense firewalls deploy first, followed by Talos cluster nodes
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
- **Talos ISOs** uploaded to Proxmox storage (required)
- **OPNSense ISO** uploaded to Proxmox storage (optional, for firewall deployment)
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
# OPNSense Firewall Configuration (Optional)
opnsense_enabled = true
opnsense_iso_file = "cephfs:iso/OPNSense-25.7-dvd-amd64.iso"

opnsense_vms = [
  {
    name        = "opnsense-fw-01"
    vmid        = 1000
    ip          = "10.83.3.5"
    cores       = 2
    memory      = 8192
    disk_size   = "30G"
    mac_address = "BC:24:21:F1:00:01"
    tags        = ["opnsense", "firewall"]
  },
  {
    name        = "opnsense-fw-02"
    vmid        = 1001
    ip          = "10.83.3.6"
    cores       = 2
    memory      = 8192
    disk_size   = "30G"
    mac_address = "BC:24:21:F1:00:02"
    tags        = ["opnsense", "firewall"]
  }
]

# Talos Cluster Configuration
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

### 2. Provision the Infrastructure

```bash
cd Resources/IAC/Terraform/Talos-Cluster-Create

# Initialize Terraform
terraform init

# Review the deployment plan
terraform plan

# Deploy the infrastructure
# Note: OPNSense VMs are deployed first, then Talos cluster nodes
terraform apply
```

**Deployment Order:**
1. **OPNSense Firewall VMs** (if enabled) - Deployed first with VMID 1000-1001
2. **Talos Kubernetes Cluster** - Deployed after OPNSense with dependencies

**Note**: OPNSense VMs require manual installation from ISO. After Terraform creates the VMs:
- Access each VM console in Proxmox
- Complete manual installation (5-10 minutes per VM)
- See [Quick Start Guide](Resources/IAC/Terraform/Talos-Cluster-Create/opnsense-configs/QUICK-START.md) for step-by-step instructions

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

### OPNSense Firewall Deployment

Deploy OPNSense firewall appliances before the Kubernetes cluster:

```hcl
opnsense_enabled = true
opnsense_iso_file = "cephfs:iso/OPNSense-25.7-dvd-amd64.iso"

opnsense_vms = [
  {
    name        = "opnsense-fw-01"
    vmid        = 1000
    ip          = "10.83.3.5"
    cores       = 2
    memory      = 8192
    disk_size   = "30G"
    mac_address = "BC:24:21:F1:00:01"
    tags        = ["opnsense", "firewall"]
  }
]
```

**Features:**
- Deployed before Talos cluster nodes (enforced via Terraform dependencies)
- Connected to vmbr0 network with VLAN 3 tagging
- 2 CPU cores, 8GB RAM, 30GB storage per VM
- Boots from ISO for initial installation

**Installation Process:**

After Terraform creates the VMs, manual installation is required:

1. **Access VM Console** in Proxmox for each OPNSense VM
2. **Login** to installer: `installer` / `opnsense`
3. **Follow Installation Wizard**:
   - Select "Install (UFS)" or "Install (ZFS)"
   - Configure WAN interface (vtnet0) with static IP
   - Set root password
   - Complete installation and reboot
4. **See** [Quick Start Guide](Resources/IAC/Terraform/Talos-Cluster-Create/opnsense-configs/QUICK-START.md) for detailed step-by-step instructions

**Time**: 5-10 minutes per VM (total ~20 minutes for both firewalls)

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
- **opnsense_vms**: Details of deployed OPNSense firewall VMs (if enabled)
- **deployment_order**: Order of VM deployment (OPNSense first, then Talos)
- **vm_mac_addresses**: MAC addresses for all Talos VMs
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

**OPNSense VM Issues**
- **ISO boots to installer**: This is expected - complete manual installation via console
  - Login: `installer` / `opnsense`
  - Follow wizard to install to disk
  - See [Installation Guide](Resources/IAC/Terraform/Talos-Cluster-Create/opnsense-configs/README.md)
- **VM keeps booting to installer**: Change boot order (Disk before CD-ROM) in Proxmox
- **Cannot access web UI**:
  - Ensure installation completed and VM rebooted from disk
  - Access at `https://10.83.3.5` or `https://10.83.3.6`
  - Default credentials: `root` / `opnsense`
- **Network not configured**: Manually configure WAN interface (vtnet0) with static IP during install
- **Ensure OPNSense ISO exists** at specified path on cephfs storage
- **Verify VMIDs 1000-1001** are not already in use

**VM Creation Fails**
- Verify Proxmox API token has correct permissions
- Ensure ISO files exist at the specified storage location
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
- [OPNSense Documentation](https://docs.opnsense.org/)
- [Proxmox VE API Documentation](https://pve.proxmox.com/pve-docs/api-viewer/)
- [Terraform Proxmox Provider](https://github.com/bpg/terraform-provider-proxmox)

---

**Last Updated**: January 2026
**Terraform Version**: >= 1.0
**Proxmox Provider Version**: 0.82.1
**Talos Version**: v1.12.1
**OPNSense Version**: 25.7

